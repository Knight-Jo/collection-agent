"""End-to-end workflow test: full pipeline with fake judge and fetcher."""

import asyncio

import pytest

from intel_agent.audit import audit_task_evidence
from intel_agent.challenge import confirm_challenge, start_challenge
from intel_agent.coverage import eval_coverage
from intel_agent.fact import save_fact
from intel_agent.models import IntelError
from intel_agent.package import generate_package
from intel_agent.task import (
    create_task,
    load_task,
    set_task_stage,
    summarize_task,
)
from tests.conftest import fake_judge, make_document, save_evidence


def _full_pipeline(cwd):
    """完成 collect→assess→challenge→done 全流程，返回任务。"""
    task = create_task(
        cwd,
        "测试主题",
        ["测试主题现状如何", "测试主题进展如何"],
        {
            "min_independent_sources": 2,
            "min_high_quality_sources": 1,
            "recency_days": 90,
            "require_recency": False,
        },
    )
    q1, q2 = task.questions[0], task.questions[1]
    docs = [
        make_document(cwd, "关于测试主题现状的报道 A", "https://news.cn/x1"),
        make_document(
            cwd, "关于测试主题现状的报道 B", "https://caixin.com/x2"
        ),
        make_document(
            cwd, "关于测试主题进展的报道 C", "https://thepaper.cn/x3"
        ),
        make_document(
            cwd, "关于测试主题进展的报道 D", "https://people.com.cn/x4"
        ),
    ]
    f1 = save_fact(cwd, task.id, q1.id, "测试主题现状为 A")
    f2 = save_fact(cwd, task.id, q2.id, "测试主题进展为 B")
    for doc, fact in [
        (docs[0], f1),
        (docs[1], f1),
        (docs[2], f2),
        (docs[3], f2),
    ]:
        save_evidence(
            cwd,
            fact.id,
            doc.id,
            "supports",
            f"关于测试主题{'现状' if fact.question_id == q1.id else '进展'}的报道",
        )
    asyncio.run(audit_task_evidence(cwd, task.id, fake_judge, "test", "fake"))

    snapshot = eval_coverage(cwd, task.id)
    assert snapshot.stop_reason == "sufficient"
    set_task_stage(cwd, task.id, "assess")

    package_result = generate_package(cwd, task.id)
    assert package_result["path"].endswith("evidence-package.md")

    from intel_agent.assess import generate_assessment
    from intel_agent.models import FactConclusion

    assert generate_assessment(
        cwd,
        task.id,
        [FactConclusion(fact_id=f1.id), FactConclusion(fact_id=f2.id)],
    )["ok"]

    set_task_stage(cwd, task.id, "challenge")
    point = {
        "question_ids": [q1.id],
        "category": "时效性",
        "challenge": "缺少近期来源",
        "gap_action": "补充近期来源",
    }
    round1 = start_challenge(cwd, task.id, 1, [point])
    new_doc = make_document(
        cwd, "关于测试主题现状的补充报道 E", "https://chinanews.com/x5"
    )
    new_evidence = save_evidence(
        cwd, f1.id, new_doc.id, "supports", "关于测试主题现状的补充报道 E"
    )
    asyncio.run(audit_task_evidence(cwd, task.id, fake_judge, "test", "fake"))
    confirmed = confirm_challenge(
        cwd,
        task.id,
        1,
        [
            {
                "point_id": round1.points[0].id,
                "status": "addressed",
                "reason": "已补充",
                "new_evidence_ids": [new_evidence.id],
            }
        ],
        [],
    )
    assert confirmed.converged

    # 收敛后必须重新出包/研判（绑定新 coverage）
    generate_package(cwd, task.id)
    assert generate_assessment(
        cwd,
        task.id,
        [FactConclusion(fact_id=f1.id), FactConclusion(fact_id=f2.id)],
    )["ok"]
    return task


def test_full_pipeline_reaches_done(cwd):
    task = _full_pipeline(cwd)
    set_task_stage(cwd, task.id, "done")
    assert load_task(cwd, task.id).stage == "done"
    assert summarize_task(cwd, task.id)["next_action"] == "任务已完成。"


def test_done_rejected_after_output_tampering(cwd):
    task = _full_pipeline(cwd)
    # 篡改产物文件 → done 被拒
    binding = load_task(cwd, task.id).outputs.package
    assert binding is not None
    path = cwd / binding.path
    path.write_text(
        path.read_text(encoding="utf-8") + "\n# tampered", encoding="utf-8"
    )
    with pytest.raises(IntelError) as e:
        set_task_stage(cwd, task.id, "done")
    assert e.value.code == "INVALID_STAGE_TRANSITION"
