"""Runtime search-configuration storage (spec 002 §6)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from .sqlite import SqliteStore


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


class SettingsStore:
    """Writable runtime configuration over the shared SQLite connection."""

    def __init__(self, db: SqliteStore) -> None:
        self.db = db

    def get(self, key: str) -> Any:
        row = self.db.execute(
            "SELECT value FROM runtime_state WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        return json.loads(row["value"])

    def set(self, key: str, value: Any) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO runtime_state (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, json.dumps(value, ensure_ascii=False)),
            )

    def current_revision(self) -> int:
        row = self.db.execute(
            "SELECT COALESCE(MAX(revision), 0) AS rev FROM config_revisions"
        ).fetchone()
        return row["rev"]

    def bump_revision(self) -> int:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO config_revisions (updated_at) VALUES (?)",
                (_iso(datetime.now(UTC)),),
            )
            row = conn.execute("SELECT last_insert_rowid() AS id").fetchone()
        return row["id"]
