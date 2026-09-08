"""Monitor persistence adapter (spec 002 §3)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from ..contracts.errors import DomainError
from ..monitoring.models import (
    FactVersion,
    Monitor,
    MonitorChange,
    MonitorRun,
    WatchSourceState,
)
from .sqlite import SqliteStore
from .tasks import _iso, _parse_iso


class MonitoringStore:
    def __init__(self, db: SqliteStore) -> None:
        self.db = db

    # --- monitors -----------------------------------------------------------

    def save_monitor(self, monitor: Monitor) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO monitors (monitor_id, name, subject, strategy,
                questions, websites, schedule, status, config_version,
                consecutive_failures, baseline_run_id, active_run_id,
                next_run_at, last_run_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(monitor_id) DO UPDATE SET
                    name = excluded.name, subject = excluded.subject,
                    strategy = excluded.strategy, questions = excluded.questions,
                    websites = excluded.websites, schedule = excluded.schedule,
                    status = excluded.status,
                    config_version = excluded.config_version,
                    consecutive_failures = excluded.consecutive_failures,
                    baseline_run_id = excluded.baseline_run_id,
                    active_run_id = excluded.active_run_id,
                    next_run_at = excluded.next_run_at,
                    last_run_at = excluded.last_run_at,
                    updated_at = excluded.updated_at
                """,
                (
                    monitor.monitor_id,
                    monitor.name,
                    monitor.subject,
                    monitor.strategy,
                    json.dumps(monitor.questions, ensure_ascii=False),
                    json.dumps(monitor.websites, ensure_ascii=False),
                    json.dumps(monitor.schedule.model_dump(mode="json")),
                    monitor.status,
                    monitor.config_version,
                    monitor.consecutive_failures,
                    monitor.baseline_run_id,
                    monitor.active_run_id,
                    _iso(monitor.next_run_at) if monitor.next_run_at else None,
                    _iso(monitor.last_run_at) if monitor.last_run_at else None,
                    _iso(monitor.created_at),
                    _iso(monitor.updated_at),
                ),
            )

    def get_monitor(self, monitor_id: str) -> Monitor:
        row = self.db.execute(
            "SELECT * FROM monitors WHERE monitor_id = ?", (monitor_id,)
        ).fetchone()
        if row is None:
            raise DomainError(
                "NOT_FOUND",
                f"monitor not found: {monitor_id}",
                stage="storage",
            )
        return Monitor(
            monitor_id=row["monitor_id"],
            name=row["name"],
            subject=row["subject"],
            strategy=row["strategy"],
            questions=json.loads(row["questions"]),
            websites=json.loads(row["websites"]),
            schedule=json.loads(row["schedule"]),
            status=row["status"],
            config_version=row["config_version"],
            consecutive_failures=row["consecutive_failures"],
            baseline_run_id=row["baseline_run_id"],
            active_run_id=row["active_run_id"],
            next_run_at=_parse_iso(row["next_run_at"])
            if row["next_run_at"]
            else None,
            last_run_at=_parse_iso(row["last_run_at"])
            if row["last_run_at"]
            else None,
            created_at=_parse_iso(row["created_at"]),
            updated_at=_parse_iso(row["updated_at"]),
        )

    def list_monitors(self) -> list[Monitor]:
        rows = self.db.execute(
            "SELECT monitor_id FROM monitors ORDER BY created_at DESC"
        ).fetchall()
        return [self.get_monitor(r["monitor_id"]) for r in rows]

    def list_due_monitors(self, now: datetime) -> list[Monitor]:
        """Active or degraded monitors whose next run is due.

        Degraded monitors keep scheduling (under backoff) so a transient
        outage self-heals once the source recovers; only paused stops work.
        """
        rows = self.db.execute(
            "SELECT monitor_id FROM monitors WHERE next_run_at IS NOT NULL"
            " AND next_run_at <= ? AND status IN ('active', 'degraded')"
            " ORDER BY next_run_at",
            (_iso(now),),
        ).fetchall()
        return [self.get_monitor(r["monitor_id"]) for r in rows]

    def update_monitor_health(
        self, monitor_id: str, consecutive_failures: int, status: str
    ) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE monitors SET consecutive_failures = ?, status = ?,"
                " updated_at = ? WHERE monitor_id = ?",
                (
                    consecutive_failures,
                    status,
                    _iso(datetime.now(UTC)),
                    monitor_id,
                ),
            )

    def update_monitor_fields(self, monitor_id: str, fields: dict) -> None:
        with self.db.transaction() as conn:
            for key, value in fields.items():
                if key in ("questions", "websites"):
                    value = json.dumps(value, ensure_ascii=False)
                conn.execute(
                    f"UPDATE monitors SET {key} = ?, updated_at = ?"
                    " WHERE monitor_id = ?",
                    (value, _iso(datetime.now(UTC)), monitor_id),
                )

    def claim_active_run(self, monitor_id: str, run_id: str) -> bool:
        """Atomically claim the single active-run slot. False on conflict."""
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT active_run_id FROM monitors WHERE monitor_id = ?",
                (monitor_id,),
            ).fetchone()
            if row is None:
                raise DomainError(
                    "NOT_FOUND",
                    f"monitor not found: {monitor_id}",
                    stage="storage",
                )
            if row["active_run_id"] is not None:
                return False
            conn.execute(
                "UPDATE monitors SET active_run_id = ?, updated_at = ?"
                " WHERE monitor_id = ?",
                (run_id, _iso(datetime.now(UTC)), monitor_id),
            )
        return True

    def release_active_run(self, monitor_id: str, run_id: str) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE monitors SET active_run_id = NULL, updated_at = ?"
                " WHERE monitor_id = ? AND active_run_id = ?",
                (_iso(datetime.now(UTC)), monitor_id, run_id),
            )

    def set_baseline(self, monitor_id: str, run_id: str) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE monitors SET baseline_run_id = ?, updated_at = ?"
                " WHERE monitor_id = ?",
                (run_id, _iso(datetime.now(UTC)), monitor_id),
            )

    def set_next_run(self, monitor_id: str, next_run_at) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE monitors SET next_run_at = ?, updated_at = ?"
                " WHERE monitor_id = ?",
                (
                    _iso(next_run_at) if next_run_at else None,
                    _iso(datetime.now(UTC)),
                    monitor_id,
                ),
            )

    # --- runs ---------------------------------------------------------------

    def save_run(self, run: MonitorRun) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO monitor_runs (run_id, monitor_id, task_id, trigger,
                scheduled_for, input_snapshot, baseline_run_id,
                initial_baseline, summary, limitations, gate_outcome)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    summary = excluded.summary,
                    limitations = excluded.limitations,
                    gate_outcome = excluded.gate_outcome
                """,
                (
                    run.run_id,
                    run.monitor_id,
                    run.task_id,
                    run.trigger,
                    _iso(run.scheduled_for) if run.scheduled_for else None,
                    json.dumps(run.input_snapshot, ensure_ascii=False),
                    run.baseline_run_id,
                    1 if run.initial_baseline else 0,
                    run.summary,
                    json.dumps(run.limitations, ensure_ascii=False),
                    run.gate_outcome,
                ),
            )

    def get_run(self, run_id: str) -> MonitorRun:
        row = self.db.execute(
            "SELECT * FROM monitor_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise DomainError(
                "NOT_FOUND",
                f"monitor run not found: {run_id}",
                stage="storage",
            )
        return MonitorRun(
            run_id=row["run_id"],
            monitor_id=row["monitor_id"],
            task_id=row["task_id"],
            trigger=row["trigger"],
            scheduled_for=_parse_iso(row["scheduled_for"])
            if row["scheduled_for"]
            else None,
            input_snapshot=json.loads(row["input_snapshot"]),
            baseline_run_id=row["baseline_run_id"],
            initial_baseline=bool(row["initial_baseline"]),
            summary=row["summary"],
            limitations=json.loads(row["limitations"]),
            gate_outcome=row["gate_outcome"],
        )

    def get_run_by_task(self, task_id: str) -> MonitorRun | None:
        row = self.db.execute(
            "SELECT run_id FROM monitor_runs WHERE task_id = ?", (task_id,)
        ).fetchone()
        return self.get_run(row["run_id"]) if row else None

    def list_runs(self, monitor_id: str) -> list[MonitorRun]:
        rows = self.db.execute(
            "SELECT run_id FROM monitor_runs WHERE monitor_id = ?"
            " ORDER BY scheduled_for DESC, run_id DESC",
            (monitor_id,),
        ).fetchall()
        return [self.get_run(r["run_id"]) for r in rows]

    # --- watch sources ------------------------------------------------------

    def get_watch_source(
        self, monitor_id: str, url: str
    ) -> WatchSourceState | None:
        row = self.db.execute(
            "SELECT * FROM monitor_watch_sources"
            " WHERE monitor_id = ? AND url = ?",
            (monitor_id, url),
        ).fetchone()
        if row is None:
            return None
        return WatchSourceState(
            monitor_id=row["monitor_id"],
            url=row["url"],
            etag=row["etag"],
            last_modified=row["last_modified"],
            byte_hash=row["byte_hash"],
            content_hash=row["content_hash"],
            last_checked_at=_parse_iso(row["last_checked_at"])
            if row["last_checked_at"]
            else None,
            last_outcome=row["last_outcome"],
        )

    def save_watch_source(self, state: WatchSourceState) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO monitor_watch_sources (monitor_id, url, etag,
                last_modified, byte_hash, content_hash, last_checked_at,
                last_outcome)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(monitor_id, url) DO UPDATE SET
                    etag = excluded.etag,
                    last_modified = excluded.last_modified,
                    byte_hash = excluded.byte_hash,
                    content_hash = excluded.content_hash,
                    last_checked_at = excluded.last_checked_at,
                    last_outcome = excluded.last_outcome
                """,
                (
                    state.monitor_id,
                    state.url,
                    state.etag,
                    state.last_modified,
                    state.byte_hash,
                    state.content_hash,
                    _iso(state.last_checked_at)
                    if state.last_checked_at
                    else None,
                    state.last_outcome,
                ),
            )

    # --- fact versions ------------------------------------------------------

    def save_fact_version(self, fact: FactVersion) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO monitor_fact_versions (fact_version_id,
                monitor_id, created_run_id, fact_key, subject, predicate,
                scope, value, statement, previous_version_id, citations)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(fact_version_id) DO UPDATE SET
                    created_run_id = excluded.created_run_id,
                    statement = excluded.statement,
                    citations = excluded.citations
                """,
                (
                    fact.fact_version_id,
                    fact.monitor_id,
                    fact.created_run_id,
                    fact.fact_key,
                    fact.subject,
                    fact.predicate,
                    json.dumps(fact.scope, ensure_ascii=False),
                    json.dumps(fact.value, ensure_ascii=False),
                    fact.statement,
                    fact.previous_version_id,
                    json.dumps(
                        [c.model_dump(mode="json") for c in fact.citations],
                        ensure_ascii=False,
                    ),
                ),
            )

    def latest_fact_version(
        self, monitor_id: str, fact_key: str
    ) -> FactVersion | None:
        row = self.db.execute(
            "SELECT * FROM monitor_fact_versions WHERE monitor_id = ?"
            " AND fact_key = ? ORDER BY fact_version_id DESC LIMIT 1",
            (monitor_id, fact_key),
        ).fetchone()
        if row is None:
            return None
        return self._fact_from_row(row)

    @staticmethod
    def _fact_from_row(row) -> FactVersion:
        from ..contracts.documents import Citation

        return FactVersion(
            fact_version_id=row["fact_version_id"],
            monitor_id=row["monitor_id"],
            created_run_id=row["created_run_id"],
            fact_key=row["fact_key"],
            subject=row["subject"],
            predicate=row["predicate"],
            scope=json.loads(row["scope"]),
            value=json.loads(row["value"]),
            statement=row["statement"],
            previous_version_id=row["previous_version_id"],
            citations=[
                Citation.model_validate(c)
                for c in json.loads(row["citations"])
            ],
        )

    # --- baseline members ---------------------------------------------------

    def save_baseline_fact(
        self, run_id: str, fact_key: str, fact_version_id: str
    ) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO monitor_baseline_facts"
                " (run_id, fact_key, fact_version_id) VALUES (?, ?, ?)",
                (run_id, fact_key, fact_version_id),
            )

    def baseline_facts(self, run_id: str) -> dict[str, FactVersion]:
        """Load a baseline run's facts keyed by fact_key.

        Joins the membership table with the immutable fact versions so the
        differ sees both statements (for overlap matching) and version ids
        (for previous_version_id links).
        """
        rows = self.db.execute(
            "SELECT fv.* FROM monitor_baseline_facts bf"
            " JOIN monitor_fact_versions fv"
            " ON fv.fact_version_id = bf.fact_version_id"
            " WHERE bf.run_id = ?",
            (run_id,),
        ).fetchall()
        return {row["fact_key"]: self._fact_from_row(row) for row in rows}

    def save_baseline_source(self, run_id: str, source_key: str) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO monitor_baseline_sources"
                " (run_id, source_key) VALUES (?, ?)",
                (run_id, source_key),
            )

    def baseline_source_keys(self, run_id: str) -> set[str]:
        rows = self.db.execute(
            "SELECT source_key FROM monitor_baseline_sources WHERE run_id = ?",
            (run_id,),
        ).fetchall()
        return {r["source_key"] for r in rows}

    # --- reported changes ---------------------------------------------------

    def reported_fingerprints(self, monitor_id: str) -> set[str]:
        rows = self.db.execute(
            "SELECT fingerprint FROM monitor_reported_changes"
            " WHERE monitor_id = ?",
            (monitor_id,),
        ).fetchall()
        return {r["fingerprint"] for r in rows}

    def mark_reported(
        self, monitor_id: str, fingerprint: str, run_id: str
    ) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO monitor_reported_changes"
                " (monitor_id, fingerprint, first_run_id, last_run_id,"
                " created_at) VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT(monitor_id, fingerprint) DO UPDATE SET"
                " last_run_id = excluded.last_run_id",
                (
                    monitor_id,
                    fingerprint,
                    run_id,
                    run_id,
                    _iso(datetime.now(UTC)),
                ),
            )

    def clear_reported(self, monitor_id: str) -> None:
        # Called when the baseline advances: everything it covered is now
        # baseline state, so old suppressions would only hide future events.
        with self.db.transaction() as conn:
            conn.execute(
                "DELETE FROM monitor_reported_changes WHERE monitor_id = ?",
                (monitor_id,),
            )

    # --- changes ------------------------------------------------------------

    def save_change(self, change: MonitorChange) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO monitor_changes (change_id, run_id, kind,
                previous_version_id, current_version_id, source_key, citation,
                importance, importance_reason, summary, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    change.change_id,
                    change.run_id,
                    change.kind,
                    change.previous_version_id,
                    change.current_version_id,
                    change.source_key,
                    json.dumps(
                        change.citation.model_dump(mode="json"),
                        ensure_ascii=False,
                    )
                    if change.citation
                    else None,
                    change.importance,
                    change.importance_reason,
                    change.summary,
                    _iso(change.created_at),
                ),
            )

    def list_changes(self, run_id: str) -> list[MonitorChange]:
        from ..contracts.documents import Citation

        rows = self.db.execute(
            "SELECT * FROM monitor_changes WHERE run_id = ?"
            " ORDER BY created_at",
            (run_id,),
        ).fetchall()
        return [
            MonitorChange(
                change_id=r["change_id"],
                run_id=r["run_id"],
                kind=r["kind"],
                previous_version_id=r["previous_version_id"],
                current_version_id=r["current_version_id"],
                source_key=r["source_key"],
                citation=Citation.model_validate(json.loads(r["citation"]))
                if r["citation"]
                else None,
                importance=r["importance"],
                importance_reason=r["importance_reason"],
                summary=r["summary"],
                created_at=_parse_iso(r["created_at"]),
            )
            for r in rows
        ]
