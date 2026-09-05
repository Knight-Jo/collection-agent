"""MaterialStore: transactional identity, documents, scope, and index state."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ..contracts.documents import (
    Chunk,
    DocumentIdentity,
    NormalizedDocument,
)
from ..contracts.errors import DomainError
from ..contracts.research import (
    BudgetUsage,
    Checkpoint,
    ContextFilter,
    MaterialScope,
    ResearchTask,
)
from ..contracts.resources import Resource, ResourceOrigin
from ._ids import artifact_id, document_id, new_id, revision_id
from .sqlite import SqliteStore


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


class MaterialStore:
    """Authoritative business storage over SQLite (spec §9.2)."""

    def __init__(self, db_path: Path) -> None:
        self.db = SqliteStore(db_path)

    def close(self) -> None:
        self.db.close()

    # --- resources ----------------------------------------------------------

    def register_resource(self, resource: Resource) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO resources
                (resource_id, content_hash, content_ref, byte_length,
                 media_type, requested_url, final_url, local_display_name,
                 acquired_at, parent_resource_id, transform, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    resource.resource_id,
                    resource.content_hash,
                    resource.content_ref,
                    resource.byte_length,
                    resource.media_type,
                    resource.origin.requested_url,
                    resource.origin.final_url,
                    resource.origin.local_display_name,
                    _iso(resource.origin.acquired_at),
                    resource.parent_resource_id,
                    json.dumps(resource.transform, ensure_ascii=False)
                    if resource.transform is not None
                    else None,
                    _iso(resource.created_at),
                ),
            )

    def get_resource(self, resource_id: str) -> Resource:
        row = self.db.execute(
            "SELECT * FROM resources WHERE resource_id = ?", (resource_id,)
        ).fetchone()
        if row is None:
            raise DomainError(
                "NOT_FOUND", f"resource not found: {resource_id}",
                stage="storage",
            )
        return Resource(
            resource_id=row["resource_id"],
            content_hash=row["content_hash"],
            byte_length=row["byte_length"],
            media_type=row["media_type"],
            content_ref=row["content_ref"],
            origin=ResourceOrigin(
                requested_url=row["requested_url"],
                final_url=row["final_url"],
                local_display_name=row["local_display_name"],
                acquired_at=_parse_iso(row["acquired_at"]),
            ),
            created_at=_parse_iso(row["created_at"]),
            parent_resource_id=row["parent_resource_id"],
            transform=json.loads(row["transform"])
            if row["transform"]
            else None,
        )

    # --- identity -----------------------------------------------------------

    def resolve_identity(self, source_key: str) -> DocumentIdentity:
        did = document_id(source_key)
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO documents (document_id, source_key,"
                " aliases) VALUES (?, ?, '[]')",
                (did, source_key),
            )
        return DocumentIdentity(document_id=did, source_key=source_key)

    def resolve_revision(self, document_id: str, resource_id: str) -> str:
        resource = self.get_resource(resource_id)
        rev = revision_id(document_id, resource.content_hash)
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO revisions
                (revision_id, document_id, content_hash, resource_id,
                 created_at) VALUES (?, ?, ?, ?, ?)
                """,
                (rev, document_id, resource.content_hash, resource_id,
                 _iso(datetime.now(UTC))),
            )
        return rev

    # --- documents ----------------------------------------------------------

    def save_document(
        self, task_id: str, document: NormalizedDocument
    ) -> str:
        payload = json.dumps(
            document.model_dump(mode="json"), ensure_ascii=False
        )
        with self.db.transaction() as conn:
            existing = conn.execute(
                "SELECT artifact_id FROM artifacts WHERE artifact_id = ?",
                (document.artifact_id,),
            ).fetchone()
            if existing is not None:
                self._associate(conn, task_id, document.artifact_id)
                return document.artifact_id
            conn.execute(
                """
                INSERT INTO artifacts
                (artifact_id, revision_id, document_id, resource_id,
                 extraction_profile_id, normalizer_version, manifest_hash,
                 status, title, published_at, language, payload, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document.artifact_id,
                    document.revision_id,
                    document.document_id,
                    document.resource_id,
                    document.extraction_profile_id,
                    document.normalizer_version,
                    document.artifact_id.split("-", 1)[1],
                    document.status,
                    document.title,
                    _iso(document.published_at)
                    if document.published_at
                    else None,
                    document.language,
                    payload,
                    _iso(datetime.now(UTC)),
                ),
            )
            for occurrence in document.provenance:
                conn.execute(
                    """
                    INSERT INTO provenance
                    (artifact_id, document_id, provider, query_id,
                     original_url, channel, observed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        document.artifact_id,
                        document.document_id,
                        occurrence.provider,
                        occurrence.query_id,
                        occurrence.original_url,
                        occurrence.channel,
                        _iso(occurrence.observed_at),
                    ),
                )
            for ordinal, block in enumerate(document.blocks):
                conn.execute(
                    """
                    INSERT INTO blocks (artifact_id, block_id, ordinal, payload)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        document.artifact_id,
                        block.block_id,
                        ordinal,
                        json.dumps(block.model_dump(mode="json"),
                                   ensure_ascii=False),
                    ),
                )
            self._associate(conn, task_id, document.artifact_id)
        return document.artifact_id

    @staticmethod
    def _associate(conn, task_id: str, artifact_id: str) -> None:
        conn.execute(
            """
            INSERT OR IGNORE INTO task_materials
            (task_id, artifact_id, ordinal, accepted, created_at)
            VALUES (?, ?, 0, 1, ?)
            """,
            (task_id, artifact_id, _iso(datetime.now(UTC))),
        )

    def get_document(self, artifact_id: str) -> NormalizedDocument:
        row = self.db.execute(
            "SELECT payload FROM artifacts WHERE artifact_id = ?",
            (artifact_id,),
        ).fetchone()
        if row is None:
            raise DomainError(
                "NOT_FOUND", f"artifact not found: {artifact_id}",
                stage="storage",
            )
        return NormalizedDocument.model_validate(json.loads(row["payload"]))

    # --- chunks -------------------------------------------------------------

    def save_chunks(self, artifact_id: str, chunks: list[Chunk]) -> None:
        with self.db.transaction() as conn:
            for chunk in chunks:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO chunks
                    (chunk_id, artifact_id, document_id, revision_id,
                     chunk_profile_id, ordinal, text, payload)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk.chunk_id,
                        chunk.artifact_id,
                        chunk.document_id,
                        chunk.revision_id,
                        chunk.chunk_profile_id,
                        chunk.ordinal,
                        chunk.text,
                        json.dumps(chunk.model_dump(mode="json"),
                                   ensure_ascii=False),
                    ),
                )

    def read_chunks(self, scope: MaterialScope) -> list[Chunk]:
        if not scope.artifact_ids:
            return []
        placeholders = ",".join("?" for _ in scope.artifact_ids)
        rows = self.db.execute(
            f"""
            SELECT payload FROM chunks
            WHERE artifact_id IN ({placeholders})
            ORDER BY artifact_id, ordinal
            """,
            tuple(scope.artifact_ids),
        ).fetchall()
        return [Chunk.model_validate(json.loads(r["payload"])) for r in rows]

    def get_chunks(self, chunk_ids: list[str]) -> list[Chunk]:
        if not chunk_ids:
            return []
        placeholders = ",".join("?" for _ in chunk_ids)
        rows = self.db.execute(
            f"SELECT payload FROM chunks WHERE chunk_id IN ({placeholders})",
            tuple(chunk_ids),
        ).fetchall()
        return [Chunk.model_validate(json.loads(r["payload"])) for r in rows]

    # --- lexical ------------------------------------------------------------

    def save_chunk_terms(self, chunk_id: str, terms: list[str]) -> None:
        with self.db.transaction() as conn:
            for term in terms:
                conn.execute(
                    "INSERT OR IGNORE INTO chunk_terms (chunk_id, term)"
                    " VALUES (?, ?)",
                    (chunk_id, term),
                )

    def search_lexical(
        self, query_terms: list[str], scope: MaterialScope, top_k: int
    ) -> list[tuple[str, int]]:
        if not scope.artifact_ids or not query_terms:
            return []
        term_ph = ",".join("?" for _ in query_terms)
        art_ph = ",".join("?" for _ in scope.artifact_ids)
        rows = self.db.execute(
            f"""
            SELECT ct.chunk_id, COUNT(*) AS matches
            FROM chunk_terms ct
            JOIN chunks c ON c.chunk_id = ct.chunk_id
            WHERE ct.term IN ({term_ph})
              AND c.artifact_id IN ({art_ph})
            GROUP BY ct.chunk_id
            ORDER BY matches DESC
            LIMIT ?
            """,
            (*query_terms, *scope.artifact_ids, top_k),
        ).fetchall()
        return [(r["chunk_id"], r["matches"]) for r in rows]

    # --- scope --------------------------------------------------------------

    def resolve_scope(
        self, task_id: str, filters: ContextFilter | None = None
    ) -> MaterialScope:
        filters = filters or ContextFilter()
        with self.db.transaction() as conn:
            scope_id = new_id("scope")
            conn.execute(
                "INSERT INTO scopes (scope_id, task_id, created_at)"
                " VALUES (?, ?, ?)",
                (scope_id, task_id, _iso(datetime.now(UTC))),
            )
            rows = self._eligible_artifacts(conn, task_id, filters)
            for ordinal, row in enumerate(rows):
                conn.execute(
                    "INSERT INTO scope_artifacts (scope_id, artifact_id,"
                    " ordinal) VALUES (?, ?, ?)",
                    (scope_id, row["artifact_id"], ordinal),
                )
        return self.get_scope(scope_id)

    def _eligible_artifacts(self, conn, task_id, filters):
        sql = """
            SELECT a.artifact_id FROM artifacts a
            JOIN task_materials tm ON tm.artifact_id = a.artifact_id
            JOIN (
                SELECT document_id, MAX(created_at) AS latest
                FROM artifacts GROUP BY document_id
            ) latest ON latest.document_id = a.document_id
                 AND latest.latest = a.created_at
            WHERE tm.task_id = ? AND tm.accepted = 1
        """
        params: list[Any] = [task_id]
        if filters.document_ids:
            placeholders = ",".join("?" for _ in filters.document_ids)
            sql += f" AND a.document_id IN ({placeholders})"
            params.extend(filters.document_ids)
        sql += " ORDER BY a.document_id"
        return conn.execute(sql, tuple(params)).fetchall()

    def save_scope(self, scope: MaterialScope) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO scopes (scope_id, task_id,"
                " created_at) VALUES (?, ?, ?)",
                (scope.scope_id, scope.task_id, _iso(scope.created_at)),
            )

    def get_scope(self, scope_id: str) -> MaterialScope:
        row = self.db.execute(
            "SELECT * FROM scopes WHERE scope_id = ?", (scope_id,)
        ).fetchone()
        if row is None:
            raise DomainError(
                "NOT_FOUND", f"scope not found: {scope_id}", stage="storage"
            )
        artifact_rows = self.db.execute(
            "SELECT artifact_id FROM scope_artifacts WHERE scope_id = ?"
            " ORDER BY ordinal",
            (scope_id,),
        ).fetchall()
        return MaterialScope(
            scope_id=scope_id,
            task_id=row["task_id"],
            artifact_ids=[r["artifact_id"] for r in artifact_rows],
            created_at=_parse_iso(row["created_at"]),
        )

    # --- tasks --------------------------------------------------------------

    def create_task(
        self, question: str, *, deadline_seconds: float | None = None
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
            created_at=now,
            updated_at=now,
            deadline_at=deadline,
        )
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO tasks (task_id, question, status, round,
                budget_used, checkpoint, created_at, updated_at, deadline_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.task_id,
                    task.question,
                    task.status,
                    task.round,
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
        checkpoint = (
            Checkpoint.model_validate(json.loads(row["checkpoint"]))
            if row["checkpoint"]
            else None
        )
        return ResearchTask(
            task_id=row["task_id"],
            question=row["question"],
            status=row["status"],
            round=row["round"],
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

    def save_checkpoint(
        self, task_id: str, checkpoint: Checkpoint, usage: BudgetUsage
    ) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE tasks SET checkpoint = ?, budget_used = ?,"
                " round = ?, updated_at = ? WHERE task_id = ?",
                (
                    json.dumps(checkpoint.model_dump(mode="json"),
                               ensure_ascii=False),
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
                (json.dumps(usage.model_dump()), _iso(datetime.now(UTC)),
                 task_id),
            )

    def list_work_items(self, task_id: str) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM work_items WHERE task_id = ? ORDER BY created_at",
            (task_id,),
        ).fetchall()
        return [dict(r) for r in rows]

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
                    work_item_id, task_id, resource_id,
                    json.dumps({
                        "source_url": source_url,
                        "profile_id": profile_id,
                        "index_after_store": index_after_store,
                    }),
                    _iso(datetime.now(UTC)), _iso(datetime.now(UTC)),
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
                "NOT_FOUND", f"work item not found: {work_item_id}",
                stage="storage",
            )
        item = dict(row)
        item["payload"] = json.loads(item.get("payload") or "{}")
        return item

    # --- index state --------------------------------------------------------

    def record_index(
        self,
        artifact_id: str,
        chunk_profile_id: str,
        *,
        embedding_profile_id: str | None = None,
        lexical_status: str = "pending",
        vector_status: str = "pending",
        chunk_count: int = 0,
        lexical_error: str | None = None,
        vector_error: str | None = None,
    ) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO index_jobs
                (artifact_id, chunk_profile_id, embedding_profile_id,
                 lexical_status, vector_status, lexical_error, vector_error,
                 chunk_count, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact_id, chunk_profile_id, embedding_profile_id,
                    lexical_status, vector_status, lexical_error,
                    vector_error, chunk_count, _iso(datetime.now(UTC)),
                ),
            )

    # --- budget ledger ------------------------------------------------------

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
                (reservation_id, task_id, kind, amount,
                 _iso(datetime.now(UTC))),
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

    # --- attempt ledger -----------------------------------------------------

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
                (work_item_id, stage, unit_key, attempt,
                 _iso(datetime.now(UTC))),
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
                (status, error, _iso(datetime.now(UTC)), work_item_id, stage,
                 unit_key, attempt),
            )
