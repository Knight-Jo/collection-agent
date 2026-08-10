"""Red-team challenge lifecycle tests."""

import asyncio

import pytest

from intel_agent.audit import audit_task_evidence
from intel_agent.challenge import confirm_challenge, start_challenge
from intel_agent.coverage import eval_coverage
from tests.conftest import save_evidence
from intel_agent.fact import save_fact
from intel_agent.models import IntelError
from tests.conftest import fake_judge, make_document, new_task


def _seed_task(cwd):
    task = new_task(cwd)
    q1, q2 = task.questions[0], task.questions[1]
    docs = [
        make_document(cwd, "关于测试主题现状的报道 A", "https://news.cn/x1"),
        make_document(cwd, "关于测试主题现状的报道 B", "https://caixin.com/x2"),
        make_document(cwd, "关于测试主题进展的报道 C", "https://thepaper.cn/x3"),
        make_document(cwd, "关于测试主题进展的报道 D", "https://people.com.cn/x4"),
    ]
    f1 = save_fact(cwd, task.id, q1.id, "测试主题现状为 A")
    f2 = save_fact(cwd, task.id, q2.id, "测试主题进展为 B")
    for doc, fact in [(docs[0], f1), (docs[1], f1), (docs[2], f2), (docs[3], f2)]:
        save_evidence(cwd, fact.id, doc.id, "supports", f"关于测试主题{'现状' if fact.question_id == q1.id else '进展'}的报道")
    asyncio.run(audit_task_evidence(cwd, task.id, fake_judge, "test", "fake"))
    eval_coverage(cwd, task.id)
    return task, f1, f2


def test_challenge_rounds_are_sequential(cwd):
    task, _, _ = _seed_task(cwd)
    point = {"question_ids": [task.questions[0].id], "category": "来源独立性", "challenge": "两个来源可能同源", "gap_action": "补充独立来源"}
    round1 = start_challenge(cwd, task.id, 1, [point])
    assert round1.round == 1
    assert round1.status == "open"
    assert round1.evidence_ids_before

    with pytest.raises(IntelError) as e:
        start_challenge(cwd, task.id, 1, [point])
    assert e.value.code == "CHALLENGE_INVALID"

    with pytest.raises(IntelError) as e:
        start_challenge(cwd, task.id, 3, [point])
    assert e.value.code == "CHALLENGE_LIMIT"


def test_confirm_requires_all_points_and_new_evidence(cwd):
    task, _, _ = _seed_task(cwd)
    point = {"question_ids": [task.questions[0].id], "category": "来源独立性", "challenge": "可能同源", "gap_action": "补充独立来源"}
    round1 = start_challenge(cwd, task.id, 1, [point])

    # 未处理全部挑战点
    with pytest.raises(IntelError) as e:
        confirm_challenge(cwd, task.id, 1, [], [])
    assert e.value.code == "CHALLENGE_INVALID"

    # addressed 必须引用本轮新增证据
    with pytest.raises(IntelError) as e:
        confirm_challenge(
            cwd, task.id, 1,
            [{"point_id": round1.points[0].id, "status": "addressed", "reason": "已补充", "new_evidence_ids": [round1.evidence_ids_before[0]]}],
            [],
        )
    assert e.value.code == "CHALLENGE_INVALID"


def test_confirm_converged_with_accepted_partial(cwd):
    task, f1, f2 = _seed_task(cwd)
    point = {"question_ids": [task.questions[0].id], "category": "时效性", "challenge": "缺少近期来源", "gap_action": "补充近期来源"}
    round1 = start_challenge(cwd, task.id, 1, [point])

    # 新增证据（本轮后）：再存一条支持证据并审核
    new_doc = make_document(cwd, "关于测试主题现状的补充报道 E", "https://chinanews.com/x5")
    new_evidence = save_evidence(cwd, f1.id, new_doc.id, "supports", "关于测试主题现状的补充报道 E")
    asyncio.run(audit_task_evidence(cwd, task.id, fake_judge, "test", "fake"))

    confirmed = confirm_challenge(
        cwd, task.id, 1,
        [{"point_id": round1.points[0].id, "status": "addressed", "reason": "已补充近期来源", "new_evidence_ids": [new_evidence.id]}],
        [],
    )
    assert confirmed.status == "confirmed"
    assert confirmed.converged


def test_dismiss_requires_reason(cwd):
    task, _, _ = _seed_task(cwd)
    point = {"question_ids": [task.questions[0].id], "category": "x", "challenge": "y", "gap_action": "z"}
    round1 = start_challenge(cwd, task.id, 1, [point])
    with pytest.raises(IntelError) as e:
        confirm_challenge(
            cwd, task.id, 1,
            [{"point_id": round1.points[0].id, "status": "dismissed", "reason": "  "}],
            [],
        )
    assert e.value.code == "CHALLENGE_INVALID"
