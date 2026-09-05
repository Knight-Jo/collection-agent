"""Budget ledger and attempt ledger tests (T03)."""

from __future__ import annotations

import pytest

from intel_agent.contracts.errors import DomainError
from intel_agent.runtime.limits import AttemptLedger, BudgetLedger


def test_reserve_settle_and_usage(material_store):
    ledger = BudgetLedger(material_store)
    task = material_store.create_task("question")
    reservation = ledger.reserve(task.task_id, "llm_tokens", 500)
    assert ledger.usage(task.task_id, "llm_tokens") == 0
    ledger.settle(reservation, 420)
    assert ledger.usage(task.task_id, "llm_tokens") == 420


def test_reserve_over_limit_is_rejected(material_store):
    ledger = BudgetLedger(material_store)
    task = material_store.create_task("question")
    ledger.settle(ledger.reserve(task.task_id, "llm_tokens", 500), 500)
    with pytest.raises(DomainError) as raised:
        ledger.reserve(task.task_id, "llm_tokens", 1, limit=500)
    assert raised.value.code == "RESOURCE_LIMIT"


def test_attempt_limit_and_resume_count(material_store):
    ledger = AttemptLedger(material_store)
    assert ledger.begin("wi-1", "fetch", "unit", limit=2) == 1
    ledger.finish("wi-1", "fetch", "unit", 1, "failed")
    assert ledger.begin("wi-1", "fetch", "unit", limit=2) == 2
    with pytest.raises(DomainError) as raised:
        ledger.begin("wi-1", "fetch", "unit", limit=2)
    assert raised.value.code == "RESOURCE_LIMIT"
