"""Semantic audit tests."""

import asyncio
import json

import pytest

from intel_agent.agent import _parse_judge_verdicts
from intel_agent.audit import (
    audit_task_evidence,
    is_full_support,
    review_for_evidence,
)
from intel_agent.fact import save_fact
from intel_agent.models import IntelError
from tests.conftest import make_document, new_task, save_evidence


def test_parse_judge_verdicts_accepts_plain_json():
    parsed = _parse_judge_verdicts(
        json.dumps(
            [
                {
                    "evidence_id": "ev-1",
                    "verdict": "full",
                    "reason": "完整支持",
                    "unsupported_parts": [],
                }
            ],
            ensure_ascii=False,
        )
    )

    assert parsed == [
        {
            "evidence_id": "ev-1",
            "verdict": "full",
            "reason": "完整支持",
            "unsupported_parts": [],
        }
    ]


def test_parse_judge_verdicts_strips_fences():
    parsed = _parse_judge_verdicts(
        '```json\n[{"evidence_id": "ev-1", "verdict": "irrelevant", '
        '"reason": "无关", "unsupported_parts": []}]\n```'
    )

    assert parsed[0]["verdict"] == "irrelevant"


def test_parse_judge_verdicts_rejects_garbage():
    with pytest.raises(IntelError) as e:
        _parse_judge_verdicts("这不是 JSON")
    assert e.value.code == "SEMANTIC_AUDIT_FAILED"

    with pytest.raises(IntelError) as e:
        _parse_judge_verdicts('{"verdicts": []}')
    assert e.value.code == "SEMANTIC_AUDIT_FAILED"


@pytest.mark.asyncio
async def test_audit_writes_reviews_and_counts(cwd):
    task = new_task(cwd)
    q = task.questions[0]
    doc = make_document(cwd, "关于测试主题的句子")
    fact = save_fact(cwd, task.id, q.id, "测试主题相关事实")
    save_evidence(cwd, fact.id, doc.id, "supports", "关于测试主题的句子")

    async def judge(fact_obj, evidence):
        return [
            {
                "evidence_id": e.id,
                "verdict": "full",
                "reason": "完整支持",
                "unsupported_parts": [],
            }
            for e in evidence
        ]

    summary = await audit_task_evidence(
        cwd, task.id, judge, "test-provider", "test-model"
    )
    assert summary["reviewed"] == 1
    assert summary["cached"] == 0
    assert summary["verdict_counts"]["full"] == 1
    review = review_for_evidence(
        cwd,
        save_evidence(
            cwd, fact.id, doc.id, "supports", "关于测试主题的句子"
        ).id,
    )
    assert review is not None
    assert review.verdict == "full"
    assert is_full_support(
        cwd,
        save_evidence(cwd, fact.id, doc.id, "supports", "关于测试主题的句子"),
    )

    # 缓存：再次审核不重复调用 judge
    calls = []

    async def judge2(fact_obj, evidence):
        calls.append(evidence)
        return [
            {
                "evidence_id": e.id,
                "verdict": "full",
                "reason": "x",
                "unsupported_parts": [],
            }
            for e in evidence
        ]

    summary2 = await audit_task_evidence(
        cwd, task.id, judge2, "test-provider", "test-model"
    )
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
        return [
            {
                "evidence_id": evidence[0].id,
                "verdict": "maybe",
                "reason": "x",
                "unsupported_parts": [],
            }
        ]

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
        return [
            {
                "evidence_id": "ev-not-mine",
                "verdict": "full",
                "reason": "x",
                "unsupported_parts": [],
            }
        ]

    with pytest.raises(IntelError) as e:
        await audit_task_evidence(
            cwd, task.id, incomplete_judge, "test", "fake"
        )
    assert e.value.code == "SEMANTIC_AUDIT_FAILED"


@pytest.mark.asyncio
async def test_audit_requires_judge_info(cwd):
    task = new_task(cwd)
    with pytest.raises(IntelError) as e:
        await audit_task_evidence(cwd, task.id, None, "", "")
    assert e.value.code == "SEMANTIC_AUDIT_FAILED"


def _full_verdicts(evidence):
    return [
        {
            "evidence_id": item.id,
            "verdict": "full",
            "reason": "完整支持",
            "unsupported_parts": [],
        }
        for item in evidence
    ]


@pytest.mark.asyncio
async def test_audit_concurrency_never_exceeds_limit(cwd):
    task = new_task(cwd)
    question = task.questions[0]
    for index in range(10):
        doc = make_document(cwd, f"关于测试主题的句子 {index}")
        fact = save_fact(cwd, task.id, question.id, f"测试主题事实 {index}")
        save_evidence(
            cwd, fact.id, doc.id, "supports", f"关于测试主题的句子 {index}"
        )

    active = 0
    max_active = 0

    async def judge(fact_obj, evidence):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.05)
        active -= 1
        return _full_verdicts(evidence)

    summary = await audit_task_evidence(
        cwd, task.id, judge, "test", "fake", concurrency=2
    )

    assert summary["reviewed"] == 10
    assert max_active <= 2


@pytest.mark.asyncio
async def test_audit_timeout_keeps_completed_reviews(cwd):
    task = new_task(cwd)
    question = task.questions[0]
    fast_doc = make_document(cwd, "关于测试主题的快速句子")
    fast_fact = save_fact(cwd, task.id, question.id, "快速事实")
    fast_evidence = save_evidence(
        cwd, fast_fact.id, fast_doc.id, "supports", "关于测试主题的快速句子"
    )
    slow_doc = make_document(cwd, "关于测试主题的慢速句子")
    slow_fact = save_fact(cwd, task.id, question.id, "慢速事实")
    slow_evidence = save_evidence(
        cwd, slow_fact.id, slow_doc.id, "supports", "关于测试主题的慢速句子"
    )

    async def judge(fact_obj, evidence):
        if fact_obj.id == slow_fact.id:
            await asyncio.Event().wait()
        return _full_verdicts(evidence)

    with pytest.raises(IntelError) as error:
        await audit_task_evidence(
            cwd,
            task.id,
            judge,
            "test",
            "fake",
            concurrency=2,
            timeout_seconds=0.2,
        )

    assert error.value.code == "SEMANTIC_AUDIT_TIMEOUT"
    fast_review = review_for_evidence(cwd, fast_evidence.id)
    assert fast_review is not None and fast_review.verdict == "full"
    assert review_for_evidence(cwd, slow_evidence.id) is None
