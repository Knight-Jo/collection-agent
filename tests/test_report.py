"""Citation-safe public information report tests."""

import asyncio
from pathlib import Path

from intel_agent.audit import audit_task_evidence
from intel_agent.coverage import eval_coverage
from intel_agent.fact import save_fact
from intel_agent.materials import register_material
from intel_agent.models import (
    FactConclusion,
    ReportedConclusion,
    ResearchReportInput,
    ResearchReportSection,
)
from intel_agent.report import generate_research_report
from tests.conftest import fake_judge, make_document, new_task, save_evidence


def seed_reportable_task(cwd):
    task = new_task(cwd)
    facts = []
    documents = []
    for index, question in enumerate(task.questions):
        statement = f"测试主题第 {index + 1} 项公开信息"
        document = make_document(
            cwd,
            f"{statement}，由公开来源正式发布。",
            f"https://www.gov.cn/report-{index + 1}",
        )
        fact = save_fact(
            cwd,
            task.id,
            question.id,
            statement,
            claim_type="primary",
        )
        save_evidence(cwd, fact.id, document, "supports", statement)
        register_material(
            cwd,
            task.id,
            document.canonical_url,
            document_id=document.id,
        )
        facts.append(fact)
        documents.append(document)
    asyncio.run(audit_task_evidence(cwd, task.id, fake_judge, "test", "fake"))
    assert eval_coverage(cwd, task.id).level == "sufficient"
    return task, facts, documents


def report_draft(task, facts):
    return ResearchReportInput(
        executive_summary="公开信息显示，测试主题已有明确进展。",
        sections=[
            ResearchReportSection(
                question_id=question.id,
                conclusions=[FactConclusion(fact_id=fact.id)],
            )
            for question, fact in zip(task.questions, facts, strict=True)
        ],
        overall_conclusions=[
            ReportedConclusion(
                fact_id=facts[0].id,
                attribution="据政府公开材料",
            )
        ],
        limitations=["公开资料存在时间滞后。"],
    )


def test_report_has_question_sections_citations_digest_and_no_internal_ids(
    cwd,
):
    task, facts, documents = seed_reportable_task(cwd)

    result = generate_research_report(cwd, task.id, report_draft(task, facts))

    assert result["ok"] is True
    content = Path(result["path"]).read_text(encoding="utf-8")
    assert "## 执行摘要" in content
    assert "## 材料导读" in content
    assert "### 内容摘要" in content
    assert "## 来源目录" in content
    assert "[1]" in content
    assert documents[0].final_url in content
    assert "fact-" not in content
    assert "doc-" not in content


def test_report_rejects_unverified_fact(cwd):
    task = new_task(cwd)
    fact = save_fact(
        cwd,
        task.id,
        task.questions[0].id,
        "没有通过审核的公开信息",
        claim_type="primary",
    )
    eval_coverage(cwd, task.id)
    draft = ResearchReportInput(
        executive_summary="摘要",
        sections=[
            ResearchReportSection(
                question_id=task.questions[0].id,
                conclusions=[FactConclusion(fact_id=fact.id)],
            )
        ],
    )

    result = generate_research_report(cwd, task.id, draft)

    assert result["ok"] is False
    assert result["errors"][0]["code"] == "INSUFFICIENT_EVIDENCE"
