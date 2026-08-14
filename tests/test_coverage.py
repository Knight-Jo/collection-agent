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


def test_answered_question_does_not_regress_for_an_extra_partial_fact(cwd):
    task = _seed_covered_task(cwd)
    initial = eval_coverage(cwd, task.id)
    extra = save_fact(
        cwd,
        task.id,
        task.questions[0].id,
        "补充发现仍待第二个来源确认",
    )
    document = make_document(
        cwd,
        "补充发现仍待第二个来源确认",
        "https://example.com/extra",
    )
    save_evidence(cwd, extra.id, document, "supports", extra.statement)
    asyncio.run(audit_task_evidence(cwd, task.id, fake_judge, "test", "fake"))

    updated = eval_coverage(cwd, task.id)

    assert initial.level == updated.level == "sufficient"
    assert initial.gap_score == updated.gap_score == 0
    assert updated.per_question[0].answer_status == "answered"
    extra_coverage = next(
        fact
        for fact in updated.per_question[0].facts
        if fact.fact_id == extra.id
    )
    assert extra_coverage.status == "partial"


def test_coverage_gap_without_evidence(cwd):
    task = new_task(cwd)
    snapshot = eval_coverage(cwd, task.id)
    assert snapshot.level == "insufficient"
    assert snapshot.stop_reason is None
    assert snapshot.per_question[0].status == "gap"


def test_primary_claim_is_covered_by_one_verified_source(cwd):
    task = new_task(cwd)
    question = task.questions[0]
    document = make_document(
        cwd, "政府发布测试主题政策", "https://www.gov.cn/policy"
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

    coverage = eval_coverage(cwd, task.id)

    assert coverage.per_question[0].facts[0].status == "covered"
    assert coverage.per_question[0].answer_status == "answered"


def test_corroborated_claim_still_requires_two_sources(cwd):
    task = new_task(cwd)
    question = task.questions[0]
    document = make_document(
        cwd, "媒体报道测试主题进展", "https://news.cn/story"
    )
    fact = save_fact(
        cwd,
        task.id,
        question.id,
        "测试主题取得进展",
        claim_type="corroborated",
    )
    save_evidence(cwd, fact.id, document, "supports", "媒体报道测试主题进展")
    asyncio.run(audit_task_evidence(cwd, task.id, fake_judge, "test", "fake"))

    coverage = eval_coverage(cwd, task.id)

    assert coverage.per_question[0].facts[0].status == "partial"
    assert coverage.per_question[0].answer_status == "partial"
    assert coverage.per_question[1].answer_status == "unanswered"


def test_question_answer_status_reports_unresolved_contradiction(cwd):
    task = new_task(cwd)
    question = task.questions[0]
    supporting = make_document(
        cwd, "政府发布测试主题政策", "https://www.gov.cn/policy"
    )
    contradicting = make_document(
        cwd, "该政策尚未发布", "https://news.cn/contradiction"
    )
    fact = save_fact(
        cwd,
        task.id,
        question.id,
        "政府发布测试主题政策",
        claim_type="primary",
    )
    save_evidence(cwd, fact.id, supporting, "supports", "政府发布测试主题政策")
    save_evidence(cwd, fact.id, contradicting, "contradicts", "该政策尚未发布")
    asyncio.run(audit_task_evidence(cwd, task.id, fake_judge, "test", "fake"))

    coverage = eval_coverage(cwd, task.id)

    assert coverage.per_question[0].answer_status == "conflicted"


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
    latest = latest_coverage(cwd, task.id)
    assert latest is not None
    assert latest.id == s2.id


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
