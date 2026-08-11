"""Coverage evaluation tests."""

import asyncio

from intel_agent.audit import audit_task_evidence
from intel_agent.coverage import eval_coverage, latest_coverage
from intel_agent.fact import save_fact
from tests.conftest import fake_judge, make_document, new_task, save_evidence


def _seed_covered_task(cwd, recency_days=90, high_quality=1):
    task = new_task(cwd)
    q1, q2 = task.questions[0], task.questions[1]
    docs = [
        make_document(
            cwd,
            "关于测试主题现状的报道 A",
            "https://news.cn/x1",
            publish_time="2026-07-01",
        ),
        make_document(
            cwd,
            "关于测试主题现状的报道 B",
            "https://caixin.com/x2",
            publish_time="2026-07-01",
        ),
        make_document(
            cwd,
            "关于测试主题进展的报道 C",
            "https://thepaper.cn/x3",
            publish_time="2026-07-01",
        ),
        make_document(
            cwd,
            "关于测试主题进展的报道 D",
            "https://people.com.cn/x4",
            publish_time="2026-07-01",
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
    return task


def test_coverage_sufficient(cwd):
    task = _seed_covered_task(cwd)
    snapshot = eval_coverage(cwd, task.id)
    assert snapshot.level == "sufficient"
    assert snapshot.stop_reason == "sufficient"
    assert snapshot.gap_score == 0
    assert all(q.status == "covered" for q in snapshot.per_question)


def test_coverage_gap_without_evidence(cwd):
    task = new_task(cwd)
    snapshot = eval_coverage(cwd, task.id)
    assert snapshot.level == "insufficient"
    assert snapshot.stop_reason is None
    assert snapshot.per_question[0].status == "gap"


def test_coverage_no_progress_stops_after_two_rounds(cwd):
    task = new_task(cwd)
    q = task.questions[0]
    doc = make_document(
        cwd, "关于测试主题的单一来源报道", "https://news.cn/x1"
    )
    fact = save_fact(cwd, task.id, q.id, "测试主题事实")
    save_evidence(
        cwd, fact.id, doc.id, "supports", "关于测试主题的单一来源报道"
    )
    asyncio.run(audit_task_evidence(cwd, task.id, fake_judge, "test", "fake"))
    s1 = eval_coverage(cwd, task.id)
    assert s1.stop_reason is None
    s2 = eval_coverage(cwd, task.id)
    assert s2.no_progress_rounds == 1
    assert s2.stop_reason is None
    s3 = eval_coverage(cwd, task.id)
    assert s3.no_progress_rounds == 2
    assert s3.stop_reason == "no_progress"


def test_coverage_fingerprint_changes(cwd):
    task = _seed_covered_task(cwd)
    s1 = eval_coverage(cwd, task.id)
    s2 = eval_coverage(cwd, task.id)
    assert s1.fingerprint == s2.fingerprint
    assert latest_coverage(cwd, task.id).id == s2.id


def test_coverage_recency_gap(cwd):
    task = _seed_covered_task(cwd)
    task.criteria.require_recency = True
    from intel_agent.task import save_task

    save_task(cwd, task)
    snapshot = eval_coverage(cwd, task.id)
    # 文档发布时间 2026-07-01，today 2026-08-10 → 40 天，仍在 90 天窗口内
    assert snapshot.stop_reason == "sufficient"

    # 改成 7 天窗口则 recency 缺口 +1
    task.criteria.recency_days = 7
    save_task(cwd, task)
    snapshot = eval_coverage(cwd, task.id)
    assert snapshot.gap_score > 0
    assert snapshot.level != "sufficient"
