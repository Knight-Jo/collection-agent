"""Citation-safe public information report tests."""

import asyncio
from pathlib import Path

from intel_agent.audit import audit_task_evidence
from intel_agent.coverage import eval_coverage
from intel_agent.fact import save_fact
from intel_agent.materials import register_material
from intel_agent.models import (
    FactConclusion,
    ResearchInferenceConclusion,
    ResearchReportedConclusion,
    ResearchReportInput,
    ResearchReportSection,
)
from intel_agent.report import _report_limitations, generate_research_report
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
        sections=[
            ResearchReportSection(
                question_id=question.id,
                conclusions=[FactConclusion(fact_id=fact.id)],
            )
            for question, fact in zip(task.questions, facts, strict=True)
        ],
        overall_conclusions=[ResearchReportedConclusion(fact_id=facts[0].id)],
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


def test_report_limitations_list_single_source_and_time_gaps(cwd):
    task = new_task(
        cwd,
        ["2026年测试主题的现状如何", "测试主题的进展如何"],
    )
    fact = save_fact(
        cwd,
        task.id,
        task.questions[0].id,
        "媒体报道测试主题现状为 A",
        claim_type="reported",
    )
    document = make_document(
        cwd,
        "媒体报道测试主题现状为 A",
        "https://news.cn/story",
        publish_time="2024-07-01",
    )
    save_evidence(cwd, fact.id, document, "supports", fact.statement)
    asyncio.run(audit_task_evidence(cwd, task.id, fake_judge, "test", "fake"))
    snapshot = eval_coverage(cwd, task.id)

    limitations = _report_limitations(snapshot)

    assert any("单源事实" in item for item in limitations)
    assert any("时间缺口" in item for item in limitations)
    assert any("问题未完全覆盖" in item for item in limitations)


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


def test_report_material_guide_excludes_low_rated_materials(cwd):
    task, facts, documents = seed_reportable_task(cwd)
    unrelated = make_document(
        cwd, "与主题无关的内容", "https://example.com/unrelated"
    )
    register_material(
        cwd,
        task.id,
        unrelated.canonical_url,
        document_id=unrelated.id,
    )

    result = generate_research_report(cwd, task.id, report_draft(task, facts))

    content = Path(result["path"]).read_text(encoding="utf-8")
    assert "另有 1 份低相关材料未展开" in content


def test_report_rejects_reported_fact_as_unattributed_fact(cwd):
    task, facts, _ = seed_reportable_task(cwd)
    reported = save_fact(
        cwd,
        task.id,
        task.questions[0].id,
        "某机构声称测试主题取得进展",
        claim_type="reported",
    )
    document = make_document(
        cwd,
        "某机构声称测试主题取得进展",
        "https://example.com/statement",
    )
    save_evidence(cwd, reported.id, document, "supports", reported.statement)
    asyncio.run(audit_task_evidence(cwd, task.id, fake_judge, "test", "fake"))
    eval_coverage(cwd, task.id)
    draft = report_draft(task, facts)
    draft.sections[0].conclusions = [FactConclusion(fact_id=reported.id)]

    result = generate_research_report(cwd, task.id, draft)

    assert result["ok"] is False
    assert any(error["code"] == "INVALID_INPUT" for error in result["errors"])


def test_report_rejects_coverage_that_predates_active_fact(cwd):
    task, facts, _ = seed_reportable_task(cwd)
    save_fact(
        cwd,
        task.id,
        task.questions[0].id,
        "覆盖评估后新增的事实",
        claim_type="reported",
    )

    result = generate_research_report(cwd, task.id, report_draft(task, facts))

    assert result["ok"] is False
    assert result["errors"][0]["code"] == "COVERAGE_STALE"


def test_report_rejects_coverage_that_predates_new_contradiction(cwd):
    task, facts, documents = seed_reportable_task(cwd)
    save_evidence(
        cwd,
        facts[0].id,
        documents[1],
        "contradicts",
        facts[1].statement,
    )

    result = generate_research_report(cwd, task.id, report_draft(task, facts))

    assert result["ok"] is False
    assert result["errors"][0]["code"] == "COVERAGE_STALE"


def test_report_requires_every_core_question(cwd):
    task, facts, _ = seed_reportable_task(cwd)
    draft = report_draft(task, facts)
    draft.sections = draft.sections[:1]

    result = generate_research_report(cwd, task.id, draft)

    assert result["ok"] is False
    assert any(error["code"] == "INVALID_INPUT" for error in result["errors"])


def test_report_rejects_unsafe_inference_text(cwd):
    task, facts, _ = seed_reportable_task(cwd)
    draft = report_draft(task, facts)
    draft.sections[0].conclusions = [
        ResearchInferenceConclusion(
            statement="伪造推断 https://evil.example doc-secret",
            confidence="medium",
            fact_ids=[facts[0].id],
        )
    ]

    result = generate_research_report(cwd, task.id, draft)

    assert result["ok"] is False
    assert any(error["code"] == "INVALID_INPUT" for error in result["errors"])


def test_report_rejects_inference_from_one_fact(cwd):
    task, facts, _ = seed_reportable_task(cwd)
    draft = report_draft(task, facts)
    draft.sections[0].conclusions = [
        ResearchInferenceConclusion(
            statement="单项事实不足以形成推断",
            confidence="low",
            fact_ids=[facts[0].id],
        )
    ]

    result = generate_research_report(cwd, task.id, draft)

    assert result["ok"] is False
    assert any(error["code"] == "INVALID_INPUT" for error in result["errors"])


def test_report_generates_substantive_summary_and_inference_basis(cwd):
    task, facts, _ = seed_reportable_task(cwd)
    draft = report_draft(task, facts)
    draft.overall_conclusions = [
        ResearchInferenceConclusion(
            statement="两项公开进展可以联合观察",
            confidence="medium",
            fact_ids=[fact.id for fact in facts],
        )
    ]

    result = generate_research_report(cwd, task.id, draft)

    assert result["ok"] is True
    content = Path(result["path"]).read_text(encoding="utf-8")
    assert "核心发现" in content
    assert facts[0].statement in content
    assert facts[1].statement in content
    assert "依据已验证事实" in content


def test_report_rejects_inference_from_a_partial_fact(cwd):
    task, facts, _ = seed_reportable_task(cwd)
    partial = save_fact(
        cwd,
        task.id,
        task.questions[0].id,
        "仍待交叉验证的补充发现",
    )
    document = make_document(
        cwd,
        partial.statement,
        "https://example.com/partial",
    )
    save_evidence(cwd, partial.id, document, "supports", partial.statement)
    asyncio.run(audit_task_evidence(cwd, task.id, fake_judge, "test", "fake"))
    eval_coverage(cwd, task.id)
    draft = report_draft(task, facts)
    draft.sections[0].conclusions = [
        ResearchInferenceConclusion(
            statement="两项材料可以形成分析判断",
            confidence="medium",
            fact_ids=[facts[0].id, partial.id],
        )
    ]

    result = generate_research_report(cwd, task.id, draft)

    assert result["ok"] is False
    assert any(
        error["code"] == "INSUFFICIENT_EVIDENCE" for error in result["errors"]
    )
