"""Task, budget, checkpoint, and execution-timeline storage (spec 002)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from ..contracts.errors import DomainError
from ..contracts.research import (
    BudgetUsage,
    Checkpoint,
    ResearchTask,
    TimelineEntry,
)
from ._ids import new_id
from .sqlite import SqliteStore


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


class TaskStore:
    """Task-scoped execution state over the shared SQLite connection."""

    def __init__(self, db: SqliteStore) -> None:
        self.db = db

    # --- tasks --------------------------------------------------------------

    def create_task(
        self,
        question: str,
        *,
        kind: str = "research",
        deadline_seconds: float | None = None,
    ) -> ResearchTask:
        now = datetime.now(UTC)
        deadline = (
            now + timedelta(seconds=deadline_seconds)
            if deadline_seconds is not None
            else None
        )
        task = ResearchTask(
            task_id=new_id("task"),
            question=question,
            status="queued",
            kind=kind,  # type: ignore[arg-type]
            created_at=now,
            updated_at=now,
            deadline_at=deadline,
        )
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO tasks (task_id, question, status, kind, round,
                phase, cancel_requested, error, attempt, budget_used,
                checkpoint, created_at, updated_at, deadline_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.task_id,
                    task.question,
                    task.status,
                    task.kind,
                    task.round,
                    task.phase,
                    0,
                    None,
                    task.attempt,
                    json.dumps(task.budget_used.model_dump()),
                    None,
                    _iso(task.created_at),
                    _iso(task.updated_at),
                    _iso(task.deadline_at) if task.deadline_at else None,
                ),
            )
        return task

    def get_task(self, task_id: str) -> ResearchTask:
        row = self.db.execute(
            "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
        if row is None:
            raise DomainError(
                "NOT_FOUND", f"task not found: {task_id}", stage="storage"
            )
        return self._task_from_row(row)

    @staticmethod
    def _task_from_row(row) -> ResearchTask:
        checkpoint = (
            Checkpoint.model_validate(json.loads(row["checkpoint"]))
            if row["checkpoint"]
            else None
        )
        return ResearchTask(
            task_id=row["task_id"],
            question=row["question"],
            status=row["status"],
            kind=row["kind"],
            round=row["round"],
            phase=row["phase"],
            cancel_requested=bool(row["cancel_requested"]),
            error=json.loads(row["error"]) if row["error"] else None,
            attempt=row["attempt"] or 0,
            budget_used=BudgetUsage.model_validate(
                json.loads(row["budget_used"])
            ),
            checkpoint=checkpoint,
            created_at=_parse_iso(row["created_at"]),
            updated_at=_parse_iso(row["updated_at"]),
            deadline_at=_parse_iso(row["deadline_at"])
            if row["deadline_at"]
            else None,
        )

    def update_task_status(
        self,
        task_id: str,
        status: str,
        *,
        phase: str | None = None,
        error: dict | None = None,
    ) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE tasks SET status = ?, phase = COALESCE(?, phase),"
                " error = COALESCE(?, error), updated_at = ? WHERE task_id = ?",
                (
                    status,
                    phase,
                    json.dumps(error) if error is not None else None,
                    _iso(datetime.now(UTC)),
                    task_id,
                ),
            )

    def set_phase(self, task_id: str, phase: str | None) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE tasks SET phase = ?, updated_at = ? WHERE task_id = ?",
                (phase, _iso(datetime.now(UTC)), task_id),
            )

    def request_cancel(self, task_id: str) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE tasks SET cancel_requested = 1, updated_at = ?"
                " WHERE task_id = ?",
                (_iso(datetime.now(UTC)), task_id),
            )

    def claim_queued(self, task_id: str) -> int:
        """Atomically claim a queued task into running; returns new attempt."""
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT attempt, status FROM tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if row is None:
                raise DomainError(
                    "NOT_FOUND", f"task not found: {task_id}", stage="storage"
                )
            if row["status"] != "queued":
                raise DomainError(
                    "CONFLICT",
                    f"task not queued: {row['status']}",
                    stage="task",
                )
            attempt = (row["attempt"] or 0) + 1
            conn.execute(
                "UPDATE tasks SET status = 'running', attempt = ?,"
                " updated_at = ? WHERE task_id = ?",
                (attempt, _iso(datetime.now(UTC)), task_id),
            )
        return attempt

    def save_checkpoint(
        self, task_id: str, checkpoint: Checkpoint, usage: BudgetUsage
    ) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE tasks SET checkpoint = ?, budget_used = ?,"
                " round = ?, updated_at = ? WHERE task_id = ?",
                (
                    json.dumps(
                        checkpoint.model_dump(mode="json"), ensure_ascii=False
                    ),
                    json.dumps(usage.model_dump()),
                    checkpoint.round,
                    _iso(datetime.now(UTC)),
                    task_id,
                ),
            )

    def record_budget_change(self, task_id: str, change: BudgetUsage) -> None:
        task = self.get_task(task_id)
        usage = BudgetUsage(
            llm_calls=task.budget_used.llm_calls + change.llm_calls,
            input_tokens=task.budget_used.input_tokens + change.input_tokens,
            output_tokens=(
                task.budget_used.output_tokens + change.output_tokens
            ),
        )
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE tasks SET budget_used = ?, updated_at = ?"
                " WHERE task_id = ?",
                (
                    json.dumps(usage.model_dump()),
                    _iso(datetime.now(UTC)),
                    task_id,
                ),
            )

    # --- budget -------------------------------------------------------------

    def reserve_budget(
        self, task_id: str, kind: str, amount: int, limit: int | None = None
    ) -> str:
        with self.db.transaction() as conn:
            if limit is not None:
                row = conn.execute(
                    "SELECT COALESCE(SUM(amount), 0) AS used"
                    " FROM budget_reservations"
                    " WHERE task_id = ? AND kind = ? AND status = 'settled'",
                    (task_id, kind),
                ).fetchone()
                if row["used"] + amount > limit:
                    raise DomainError(
                        "RESOURCE_LIMIT",
                        f"{kind} budget exhausted for task {task_id}",
                        stage="budget",
                    )
            reservation_id = new_id("resv")
            conn.execute(
                "INSERT INTO budget_reservations"
                " (reservation_id, task_id, kind, amount, status, created_at)"
                " VALUES (?, ?, ?, ?, 'reserved', ?)",
                (
                    reservation_id,
                    task_id,
                    kind,
                    amount,
                    _iso(datetime.now(UTC)),
                ),
            )
        return reservation_id

    def settle_budget(self, reservation_id: str, actual: int) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE budget_reservations SET status = 'settled',"
                " amount = ? WHERE reservation_id = ?",
                (actual, reservation_id),
            )

    def budget_usage(self, task_id: str, kind: str) -> int:
        row = self.db.execute(
            "SELECT COALESCE(SUM(amount), 0) AS used FROM budget_reservations"
            " WHERE task_id = ? AND kind = ? AND status = 'settled'",
            (task_id, kind),
        ).fetchone()
        return row["used"]

    # --- attempts -----------------------------------------------------------

    def begin_attempt(
        self, work_item_id: str, stage: str, unit_key: str, limit: int
    ) -> int:
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(attempt), 0) AS max_attempt"
                " FROM attempts WHERE work_item_id = ? AND stage = ?"
                " AND unit_key = ?",
                (work_item_id, stage, unit_key),
            ).fetchone()
            attempt = row["max_attempt"] + 1
            if attempt > limit:
                raise DomainError(
                    "RESOURCE_LIMIT",
                    f"attempt limit reached for {stage}/{unit_key}",
                    stage="attempt",
                )
            conn.execute(
                "INSERT INTO attempts"
                " (work_item_id, stage, unit_key, attempt, status,"
                " started_at) VALUES (?, ?, ?, ?, 'started', ?)",
                (
                    work_item_id,
                    stage,
                    unit_key,
                    attempt,
                    _iso(datetime.now(UTC)),
                ),
            )
        return attempt

    def finish_attempt(
        self,
        work_item_id: str,
        stage: str,
        unit_key: str,
        attempt: int,
        status: str,
        error: str | None = None,
    ) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE attempts SET status = ?, error = ?, ended_at = ?"
                " WHERE work_item_id = ? AND stage = ? AND unit_key = ?"
                " AND attempt = ?",
                (
                    status,
                    error,
                    _iso(datetime.now(UTC)),
                    work_item_id,
                    stage,
                    unit_key,
                    attempt,
                ),
            )

    # --- work items ---------------------------------------------------------

    def create_work_item(
        self,
        task_id: str,
        source_url: str,
        profile_id: str,
        index_after_store: bool,
        resource_id: str | None = None,
    ) -> str:
        work_item_id = new_id("wi")
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO work_items
                (work_item_id, task_id, stage, status, resource_id,
                 payload, created_at, updated_at)
                VALUES (?, ?, 'pending', 'pending', ?, ?, ?, ?)
                """,
                (
                    work_item_id,
                    task_id,
                    resource_id,
                    json.dumps(
                        {
                            "source_url": source_url,
                            "profile_id": profile_id,
                            "index_after_store": index_after_store,
                        }
                    ),
                    _iso(datetime.now(UTC)),
                    _iso(datetime.now(UTC)),
                ),
            )
        return work_item_id

    def update_work_item(
        self,
        work_item_id: str,
        stage: str,
        status: str,
        *,
        resource_id: str | None = None,
        artifact_id: str | None = None,
    ) -> None:
        sets = ["stage = ?", "status = ?", "updated_at = ?"]
        params: list[Any] = [stage, status, _iso(datetime.now(UTC))]
        if resource_id is not None:
            sets.append("resource_id = ?")
            params.append(resource_id)
        if artifact_id is not None:
            sets.append("artifact_id = ?")
            params.append(artifact_id)
        params.append(work_item_id)
        with self.db.transaction() as conn:
            conn.execute(
                f"UPDATE work_items SET {', '.join(sets)}"
                " WHERE work_item_id = ?",
                tuple(params),
            )

    def get_work_item(self, work_item_id: str) -> dict:
        row = self.db.execute(
            "SELECT * FROM work_items WHERE work_item_id = ?",
            (work_item_id,),
        ).fetchone()
        if row is None:
            raise DomainError(
                "NOT_FOUND",
                f"work item not found: {work_item_id}",
                stage="storage",
            )
        item = dict(row)
        item["payload"] = json.loads(item.get("payload") or "{}")
        return item

    # --- task materials -----------------------------------------------------

    def list_task_artifacts(self, task_id: str) -> list[str]:
        rows = self.db.execute(
            "SELECT artifact_id FROM task_materials WHERE task_id = ?"
            " ORDER BY ordinal",
            (task_id,),
        ).fetchall()
        return [r["artifact_id"] for r in rows]

    def latest_task_id(self, conversation_id: str) -> str | None:
        row = self.db.execute(
            "SELECT task_id FROM messages WHERE conversation_id = ?"
            " AND task_id IS NOT NULL ORDER BY sequence DESC LIMIT 1",
            (conversation_id,),
        ).fetchone()
        return row["task_id"] if row else None

    # --- task timeline ------------------------------------------------------

    def add_timeline(
        self,
        task_id: str,
        phase: str,
        state: str,
        summary: str = "",
        attempt: int = 0,
    ) -> TimelineEntry:
        now = _iso(datetime.now(UTC))
        entry_id = new_id("ttl")
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(sequence), 0) AS seq FROM task_timeline"
                " WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            sequence = row["seq"] + 1
            conn.execute(
                "INSERT INTO task_timeline (entry_id, task_id, sequence,"
                " attempt, phase, state, summary, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    entry_id,
                    task_id,
                    sequence,
                    attempt,
                    phase,
                    state,
                    summary,
                    now,
                ),
            )
        return TimelineEntry(
            entry_id=entry_id,
            task_id=task_id,
            sequence=sequence,
            attempt=attempt,
            phase=phase,
            state=state,
            summary=summary,
            created_at=_parse_iso(now),
        )

    def list_timeline(self, task_id: str) -> list[TimelineEntry]:
        rows = self.db.execute(
            "SELECT * FROM task_timeline WHERE task_id = ? ORDER BY sequence",
            (task_id,),
        ).fetchall()
        return [
            TimelineEntry(
                entry_id=r["entry_id"],
                task_id=r["task_id"],
                sequence=r["sequence"],
                attempt=r["attempt"],
                phase=r["phase"],
                state=r["state"],
                summary=r["summary"],
                created_at=_parse_iso(r["created_at"]),
            )
            for r in rows
        ]

    def list_task_ids_by_status(self, status: str) -> list[str]:
        rows = self.db.execute(
            "SELECT task_id FROM tasks WHERE status = ?", (status,)
        ).fetchall()
        return [r["task_id"] for r in rows]

    # --- idempotency --------------------------------------------------------

    def register_idempotent(
        self, operation: str, key: str, input_hash: str, result_ref: str
    ) -> bool:
        """Record an idempotent submission. Returns False on conflict."""
        try:
            with self.db.transaction() as conn:
                conn.execute(
                    "INSERT INTO idempotency (operation, idempotency_key,"
                    " input_hash, result_ref, created_at)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (
                        operation,
                        key,
                        input_hash,
                        result_ref,
                        _iso(datetime.now(UTC)),
                    ),
                )
            return True
        except Exception:  # noqa: BLE001
            return False

    def find_idempotent(self, operation: str, key: str) -> dict | None:
        row = self.db.execute(
            "SELECT * FROM idempotency WHERE operation = ? AND idempotency_key = ?",
            (operation, key),
        ).fetchone()
        if row is None:
            return None
        return {
            "input_hash": row["input_hash"],
            "result_ref": row["result_ref"],
        }
