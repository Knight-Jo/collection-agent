"""Task-scoped material recommendations and collection digest."""

import asyncio

import pytest

from intel_agent.audit import audit_task_evidence
from intel_agent.fact import save_fact
from intel_agent.materials import (
    generate_material_digest,
    load_material_digest,
    register_material,
)
from intel_agent.models import (
    CrawlEntry,
    CrawlSnapshot,
    ExtractionState,
    IntelError,
    utc_now,
)
from intel_agent.storage import save_crawl, write_file_atomic
from tests.conftest import fake_judge, make_document, new_task, save_evidence


def _seed_verified_material(cwd):
    task = new_task(cwd)
    question = task.questions[0]
    document = make_document(
        cwd,
        "政府发布测试主题政策，明确测试主题的实施安排。",
        "https://www.gov.cn/policy",
    )
    fact = save_fact(
        cwd,
        task.id,
        question.id,
        "政府发布测试主题政策",
        claim_type="primary",
    )
    save_evidence(cwd, fact.id, document, "supports", "政府发布测试主题政策")
    asyncio.run(audit_task_evidence(cwd, task.id, fake_judge, "test", "fake"))
    register_material(
        cwd, task.id, document.canonical_url, document_id=document.id
    )
    return task, question, document, fact


def test_verified_core_material_receives_five_stars(cwd):
    task, question, document, fact = _seed_verified_material(cwd)

    digest = generate_material_digest(cwd, task.id)

    review = next(
        item for item in digest.materials if item.document_id == document.id
    )
    assert review.rating == 5
    assert len(review.description) <= 120
    assert review.question_ids == [question.id]
    assert fact.statement in digest.key_points
    assert document.canonical_url in digest.priority_materials


def test_failed_material_receives_one_star(cwd):
    task = new_task(cwd)
    record = register_material(
        cwd,
        task.id,
        "https://example.com/fail",
        error="正文提取失败",
    )

    digest = generate_material_digest(cwd, task.id)
    review = next(
        item
        for item in digest.materials
        if item.canonical_url == record.canonical_url
    )

    assert review.rating == 1
    assert "正文提取失败" in review.description


def test_material_recommendations_are_task_scoped(cwd):
    first_task, _, document, _ = _seed_verified_material(cwd)
    second_task = new_task(cwd, ["其他问题甲", "其他问题乙"])
    register_material(
        cwd,
        second_task.id,
        document.canonical_url,
        document_id=document.id,
    )

    first = generate_material_digest(cwd, first_task.id)
    second = generate_material_digest(cwd, second_task.id)

    assert first.materials[0].rating == 5
    assert second.materials[0].rating == 3
    assert load_material_digest(cwd, first_task.id) == first
    assert load_material_digest(cwd, second_task.id) == second


def test_digest_recommends_only_four_and_five_star_materials(cwd):
    task, _, document, _ = _seed_verified_material(cwd)
    background = make_document(
        cwd,
        "与当前调研没有关键词重合的普通背景材料。",
        "https://example.com/background",
    )
    register_material(
        cwd, task.id, background.canonical_url, document_id=background.id
    )

    digest = generate_material_digest(cwd, task.id)

    assert digest.priority_materials == [document.canonical_url]
    assert all(
        review.rating >= 4
        for review in digest.materials
        if review.canonical_url in digest.priority_materials
    )


def test_digest_includes_failed_crawl_resources(cwd):
    task = new_task(cwd)
    now = utc_now()
    save_crawl(
        cwd,
        CrawlSnapshot(
            task_id=task.id,
            status="complete",
            entries=[
                CrawlEntry(
                    canonical_url="https://example.com/failed.pdf",
                    depth=0,
                    priority=0,
                    status="failed",
                    error="下载超时",
                    extraction=ExtractionState(status="failed"),
                    created_at=now,
                    updated_at=now,
                )
            ],
            created_at=now,
            updated_at=now,
        ),
    )

    digest = generate_material_digest(cwd, task.id)

    assert digest.materials[0].rating == 1
    assert "下载超时" in digest.materials[0].description


def test_digest_does_not_hide_corrupt_crawl_state(cwd):
    task = new_task(cwd)
    write_file_atomic(cwd, f"data/intel/crawls/{task.id}.json", "{")

    with pytest.raises(IntelError) as error:
        generate_material_digest(cwd, task.id)

    assert error.value.code == "STORAGE_CORRUPT"
