"""Semantic audit tests."""

import pytest

from intel_agent.audit import audit_task_evidence, is_full_support, review_for_evidence
from tests.conftest import save_evidence
from intel_agent.fact import save_fact
from intel_agent.models import IntelError
from tests.conftest import make_document, new_task


@pytest.mark.asyncio
async def test_audit_writes_reviews_and_counts(cwd):
    task = new_task(cwd)
    q = task.questions[0]
    doc = make_document(cwd, "关于测试主题的句子")
    fact = save_fact(cwd, task.id, q.id, "测试主题相关事实")
    save_evidence(cwd, fact.id, doc.id, "supports", "关于测试主题的句子")

    async def judge(fact_obj, evidence):
        return [{"evidence_id": e.id, "verdict": "full", "reason": "完整支持", "unsupported_parts": []} for e in evidence]

    summary = await audit_task_evidence(cwd, task.id, judge, "test-provider", "test-model")
    assert summary["reviewed"] == 1
    assert summary["cached"] == 0
    assert summary["verdict_counts"]["full"] == 1
    review = review_for_evidence(cwd, save_evidence(cwd, fact.id, doc.id, "supports", "关于测试主题的句子").id)
    assert review is not None
    assert review.verdict == "full"
    assert is_full_support(cwd, save_evidence(cwd, fact.id, doc.id, "supports", "关于测试主题的句子"))

    # 缓存：再次审核不重复调用 judge
    calls = []

    async def judge2(fact_obj, evidence):
        calls.append(evidence)
        return [{"evidence_id": e.id, "verdict": "full", "reason": "x", "unsupported_parts": []} for e in evidence]

    summary2 = await audit_task_evidence(cwd, task.id, judge2, "test-provider", "test-model")
    assert summary2["cached"] == 1
    assert summary2["reviewed"] == 0
    assert calls == []


@pytest.mark.asyncio
async def test_audit_rejects_invalid_verdict(cwd):
    task = new_task(cwd)
    q = task.questions[0]
    doc = make_document(cwd, "关于测试主题的句子")
    fact = save_fact(cwd, task.id, q.id, "测试主题相关事实")
    save_evidence(cwd, fact.id, doc.id, "supports", "关于测试主题的句子")

    async def bad_judge(fact_obj, evidence):
        return [{"evidence_id": e.id, "verdict": "maybe", "reason": "x", "unsupported_parts": []}]

    with pytest.raises(IntelError) as e:
        await audit_task_evidence(cwd, task.id, bad_judge, "test", "fake")
    assert e.value.code == "SEMANTIC_AUDIT_FAILED"


@pytest.mark.asyncio
async def test_audit_rejects_missing_evidence_ids(cwd):
    task = new_task(cwd)
    q = task.questions[0]
    doc = make_document(cwd, "关于测试主题的句子")
    fact = save_fact(cwd, task.id, q.id, "测试主题相关事实")
    save_evidence(cwd, fact.id, doc.id, "supports", "关于测试主题的句子")

    async def incomplete_judge(fact_obj, evidence):
        return [{"evidence_id": "ev-not-mine", "verdict": "full", "reason": "x", "unsupported_parts": []}]

    with pytest.raises(IntelError) as e:
        await audit_task_evidence(cwd, task.id, incomplete_judge, "test", "fake")
    assert e.value.code == "SEMANTIC_AUDIT_FAILED"


@pytest.mark.asyncio
async def test_audit_requires_judge_info(cwd):
    task = new_task(cwd)
    with pytest.raises(IntelError) as e:
        await audit_task_evidence(cwd, task.id, None, "", "")
    assert e.value.code == "SEMANTIC_AUDIT_FAILED"
