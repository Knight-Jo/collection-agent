"""Durable budget and attempt ledger tests (T03)."""

from __future__ import annotations

import pytest

from intel_agent.contracts.errors import DomainError


def test_reserve_settle_and_usage(task_store):
    task = task_store.create_task("question")
    reservation = task_store.reserve_budget(task.task_id, "llm_tokens", 500)
    assert task_store.budget_usage(task.task_id, "llm_tokens") == 0
    task_store.settle_budget(reservation, 420)
    assert task_store.budget_usage(task.task_id, "llm_tokens") == 420


def test_reserve_over_limit_is_rejected(task_store):
    task = task_store.create_task("question")
    task_store.settle_budget(
        task_store.reserve_budget(task.task_id, "llm_tokens", 500), 500
    )
    with pytest.raises(DomainError) as raised:
        task_store.reserve_budget(task.task_id, "llm_tokens", 1, limit=500)
    assert raised.value.code == "RESOURCE_LIMIT"


def test_attempt_limit_and_resume_count(task_store):
    assert task_store.begin_attempt("wi-1", "fetch", "unit", limit=2) == 1
    task_store.finish_attempt("wi-1", "fetch", "unit", 1, "failed")
    assert task_store.begin_attempt("wi-1", "fetch", "unit", limit=2) == 2
    with pytest.raises(DomainError) as raised:
        task_store.begin_attempt("wi-1", "fetch", "unit", limit=2)
    assert raised.value.code == "RESOURCE_LIMIT"
