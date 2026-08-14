"""Task lifecycle, budgets, stage machine tests."""

import pytest

from intel_agent.models import IntelError, SufficiencyCriteria
from intel_agent.task import (
    FETCH_ATTEMPT_LIMIT,
    SEARCH_ATTEMPT_LIMIT,
    create_task,
    load_task,
    record_evidence_progress,
    record_fetch_attempt,
    record_search_attempt,
    set_task_stage,
)
from tests.conftest import new_task


def test_create_task_does_not_alias_caller_criteria(cwd):
    criteria = SufficiencyCriteria(
        min_independent_sources=2,
        min_high_quality_sources=1,
        recency_days=90,
        require_recency=False,
    )

    task = create_task(cwd, "主题", ["问题甲", "问题乙"], criteria)
    task.criteria.require_recency = True

    assert criteria.require_recency is False


def test_create_task_validates_input(cwd):
    with pytest.raises(IntelError) as e:
        create_task(
            cwd,
            "   ",
            ["a"],
            {
                "min_independent_sources": 2,
                "min_high_quality_sources": 1,
                "recency_days": 90,
                "require_recency": False,
            },
        )
    assert e.value.code == "INVALID_INPUT"

    with pytest.raises(IntelError) as e:
        create_task(
            cwd,
            "主题",
            ["a", "b", "c", "d", "e", "f", "g"],
            {
                "min_independent_sources": 2,
                "min_high_quality_sources": 1,
                "recency_days": 90,
                "require_recency": False,
            },
        )
    assert e.value.code == "INVALID_INPUT"

    with pytest.raises(IntelError) as e:
        create_task(
            cwd,
            "主题",
            ["a", "b"],
            {
                "min_independent_sources": 0,
                "min_high_quality_sources": 1,
                "recency_days": 90,
                "require_recency": False,
            },
        )
    assert e.value.code == "INVALID_INPUT"


def test_create_task_dedupes_questions_and_persists(cwd):
    task = create_task(
        cwd,
        "主题",
        ["q1", "q1", "", "q2"],
        {
            "min_independent_sources": 2,
            "min_high_quality_sources": 1,
            "recency_days": 90,
            "require_recency": False,
        },
    )
    assert task.stage == "collect"
    assert len(task.questions) == 2
    assert task.collection.search_attempts == 0
    assert load_task(cwd).id == task.id
    assert load_task(cwd, task.id).id == task.id


def test_search_budget_exhausts(cwd):
    task = new_task(cwd)
    for _ in range(SEARCH_ATTEMPT_LIMIT):
        record_search_attempt(cwd, task.id)
    with pytest.raises(IntelError) as e:
        record_search_attempt(cwd, task.id)
    assert e.value.code == "SEARCH_BUDGET_EXHAUSTED"
    assert (
        load_task(cwd, task.id).collection.search_stop_reason
        == "search_budget_exhausted"
    )


def test_fetch_budget_resets_on_evidence(cwd):
    task = new_task(cwd)
    for _ in range(FETCH_ATTEMPT_LIMIT):
        record_fetch_attempt(cwd, task.id)
    with pytest.raises(IntelError) as e:
        record_fetch_attempt(cwd, task.id)
    assert e.value.code == "COLLECTION_BUDGET_EXHAUSTED"
    assert (
        load_task(cwd, task.id).collection.stop_reason
        == "fetch_without_evidence"
    )
    record_evidence_progress(cwd, task.id, 1)
    assert (
        load_task(cwd, task.id).collection.fetch_attempts_since_evidence == 0
    )
    assert load_task(cwd, task.id).collection.stop_reason is None


def test_stage_transitions_are_adjacent_only(cwd):
    task = new_task(cwd)
    with pytest.raises(IntelError) as e:
        set_task_stage(cwd, task.id, "done")
    assert e.value.code == "INVALID_STAGE_TRANSITION"
    with pytest.raises(IntelError) as e:
        set_task_stage(cwd, task.id, "assess")
    assert e.value.code == "INVALID_STAGE_TRANSITION"


def test_stage_assess_requires_stop_reason(cwd):
    task = new_task(cwd)
    from intel_agent.coverage import eval_coverage

    eval_coverage(cwd, task.id)
    with pytest.raises(IntelError) as e:
        set_task_stage(cwd, task.id, "assess")
    assert e.value.code == "INVALID_STAGE_TRANSITION"


def test_done_requires_challenge_and_outputs(cwd):
    task = new_task(cwd)
    from intel_agent.audit import audit_task_evidence
    from intel_agent.coverage import eval_coverage
    from intel_agent.fact import save_fact
    from tests.conftest import fake_judge, make_document, save_evidence

    q1, q2 = task.questions[0], task.questions[1]
    docs = [
        make_document(
            cwd,
            f"document {i} text about 测试主题 progress",
            f"https://news.cn/x{i}",
        )
        for i in range(4)
    ]
    fact1 = save_fact(cwd, task.id, q1.id, "测试主题现状为 A")
    fact2 = save_fact(cwd, task.id, q2.id, "测试主题进展为 B")
    for i, fact in enumerate([fact1, fact1, fact2, fact2]):
        save_evidence(
            cwd,
            fact.id,
            docs[i],
            "supports",
            f"document {i} text about 测试主题 progress",
        )
    import asyncio

    asyncio.run(audit_task_evidence(cwd, task.id, fake_judge, "test", "fake"))
    eval_coverage(cwd, task.id)
    with pytest.raises(IntelError) as e:
        set_task_stage(cwd, task.id, "done")
    assert e.value.code == "INVALID_STAGE_TRANSITION"


def test_current_report_can_complete_directly_from_assess(cwd):
    from intel_agent.report import generate_research_report
    from tests.test_report import report_draft, seed_reportable_task

    task, facts, _ = seed_reportable_task(cwd)
    set_task_stage(cwd, task.id, "assess")
    generate_research_report(cwd, task.id, report_draft(task, facts))

    completed = set_task_stage(cwd, task.id, "done")

    assert completed.completion_status == "sufficient"


def test_done_rejects_report_bound_to_stale_coverage(cwd):
    from intel_agent.coverage import eval_coverage
    from intel_agent.fact import save_fact
    from intel_agent.report import generate_research_report
    from tests.test_report import report_draft, seed_reportable_task

    task, facts, _ = seed_reportable_task(cwd)
    set_task_stage(cwd, task.id, "assess")
    generate_research_report(cwd, task.id, report_draft(task, facts))
    save_fact(
        cwd,
        task.id,
        task.questions[0].id,
        "报告生成后新增的事实",
        claim_type="primary",
    )
    eval_coverage(cwd, task.id)

    with pytest.raises(IntelError) as error:
        set_task_stage(cwd, task.id, "done")

    assert error.value.code == "INVALID_STAGE_TRANSITION"
