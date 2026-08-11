"""Read-model tests for the Web task workbench."""

from __future__ import annotations

import asyncio

import pytest

from intel_agent.audit import audit_task_evidence
from intel_agent.coverage import eval_coverage
from intel_agent.fact import save_fact
from intel_agent.models import IntelError
from intel_agent.package import generate_package
from intel_agent.web.views import (
    get_artifact,
    get_task_view,
    list_task_summaries,
)
from tests.conftest import fake_judge, make_document, new_task, save_evidence


def test_list_task_summaries_returns_newest_first(cwd):
    first = new_task(cwd)
    second = new_task(cwd, ["问题丙", "问题丁"])

    summaries = list_task_summaries(cwd)

    assert [item.id for item in summaries] == [second.id, first.id]
    assert summaries[0].coverage_level is None


def test_get_task_view_nests_fact_evidence_review_and_document(cwd):
    task = new_task(cwd)
    fact = save_fact(cwd, task.id, task.questions[0].id, "测试主题已有进展")
    document = make_document(cwd, "测试主题已有进展，来源已确认。")
    evidence = save_evidence(
        cwd,
        fact.id,
        document,
        "supports",
        "测试主题已有进展",
    )
    asyncio.run(audit_task_evidence(cwd, task.id, fake_judge, "test", "fake"))
    eval_coverage(cwd, task.id)

    view = get_task_view(cwd, task.id)

    fact_view = view.questions[0].facts[0]
    assert fact_view.id == fact.id
    assert fact_view.evidence[0].id == evidence.id
    assert fact_view.evidence[0].review is not None
    assert fact_view.evidence[0].review.verdict == "full"
    assert fact_view.evidence[0].document.title == "测试文档"
    assert view.coverage is not None


def test_get_artifact_verifies_bound_content(cwd):
    task = new_task(cwd)
    eval_coverage(cwd, task.id)
    generate_package(cwd, task.id)

    artifact = get_artifact(cwd, task.id, "package")

    assert artifact.content.startswith("# 证据包")
    assert artifact.path == "output/测试主题-evidence-package.md"

    path = cwd / "output/测试主题-evidence-package.md"
    path.write_text("tampered", encoding="utf-8")
    with pytest.raises(IntelError) as error:
        get_artifact(cwd, task.id, "package")
    assert error.value.code == "OUTPUT_TAMPERED"
