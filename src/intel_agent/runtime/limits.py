"""Durable budget and attempt ledgers (T03)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ..storage.materials import MaterialStore


@dataclass(frozen=True)
class OperationContext:
    """Binds a budgeted operation to its task, item, and deadline."""

    task_id: str
    work_item_id: str
    deadline_at: datetime

    @property
    def remaining_seconds(self) -> float:
        return (self.deadline_at - datetime.now(UTC)).total_seconds()


class BudgetLedger:
    """Reserve-then-settle accounting, persisted in MaterialStore."""

    def __init__(self, store: MaterialStore) -> None:
        self.store = store

    def reserve(
        self, task_id: str, kind: str, amount: int, limit: int | None = None
    ) -> str:
        return self.store.reserve_budget(task_id, kind, amount, limit)

    def settle(self, reservation_id: str, actual: int) -> None:
        self.store.settle_budget(reservation_id, actual)

    def usage(self, task_id: str, kind: str) -> int:
        return self.store.budget_usage(task_id, kind)


class AttemptLedger:
    """Counts per-unit attempts; recovery resumes the same cumulative count."""

    def __init__(self, store: MaterialStore) -> None:
        self.store = store

    def begin(
        self, work_item_id: str, stage: str, unit_key: str, limit: int
    ) -> int:
        return self.store.begin_attempt(work_item_id, stage, unit_key, limit)

    def finish(
        self,
        work_item_id: str,
        stage: str,
        unit_key: str,
        attempt: int,
        status: str,
        error: str | None = None,
    ) -> None:
        self.store.finish_attempt(
            work_item_id, stage, unit_key, attempt, status, error
        )
