"""Assessment generation tests."""

import asyncio
from pathlib import Path

from intel_agent.assess import generate_assessment
from intel_agent.audit import audit_task_evidence
from intel_agent.coverage import eval_coverage
from intel_agent.fact import save_fact
from intel_agent.models import (
    FactConclusion,
    InferenceConclusion,
    ReportedConclusion,
)
from tests.conftest import fake_judge, make_document, new_task, save_evidence


def _seed_task(cwd):
    task = new_task(cwd)
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
    coverage = eval_coverage(cwd, task.id)
    assert coverage.level == "sufficient"
    return task, f1, f2


def test_assessment_requires_coverage(cwd):
    task = new_task(cwd)
    result = generate_assessment(cwd, task.id, [])
    assert not result["ok"]
    assert any(e["code"] == "INVALID_INPUT" for e in result["errors"])


def test_assessment_generates_file(cwd):
    task, f1, f2 = _seed_task(cwd)
    result = generate_assessment(
        cwd,
        task.id,
        [FactConclusion(fact_id=f1.id), FactConclusion(fact_id=f2.id)],
    )
    assert result["ok"]
    assert result["path"].endswith("assessment.md")
    content = Path(result["path"]).read_text(encoding="utf-8")
    assert "研判报告" in content
    assert f1.id in content


def test_assessment_rejects_uncovered_fact(cwd):
    task = new_task(cwd)
    q = task.questions[0]
    doc = make_document(cwd, "关于测试主题的单一来源")
    fact = save_fact(cwd, task.id, q.id, "测试主题事实")
    save_evidence(cwd, fact.id, doc.id, "supports", "关于测试主题的单一来源")
    asyncio.run(audit_task_evidence(cwd, task.id, fake_judge, "test", "fake"))
    eval_coverage(cwd, task.id)
    # 该 fact 未达到 covered（独立来源不足）→ fact 结论被拒绝
    result = generate_assessment(
        cwd, task.id, [FactConclusion(fact_id=fact.id)]
    )
    assert not result["ok"]
    assert result["errors"][0]["code"] == "INSUFFICIENT_EVIDENCE"


def test_assessment_supports_reported_and_inference(cwd):
    task, f1, f2 = _seed_task(cwd)
    result = generate_assessment(
        cwd,
        task.id,
        [
            ReportedConclusion(fact_id=f1.id, attribution="据某单一来源报道"),
            InferenceConclusion(
                statement="测试主题将加速发展",
                rationale="基于现状与进展推断",
                confidence="medium",
                fact_ids=[f1.id, f2.id],
            ),
        ],
    )
    assert result["ok"]
    content = Path(result["path"]).read_text(encoding="utf-8")
    assert "单源转述" in content
    assert "推断" in content


def test_assessment_rejects_invalid_fact_id(cwd):
    task = new_task(cwd)
    result = generate_assessment(
        cwd, task.id, [FactConclusion(fact_id="fact-nope")]
    )
    assert not result["ok"]
    assert result["errors"][0]["code"] == "INVALID_INPUT"
