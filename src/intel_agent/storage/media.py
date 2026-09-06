"""Media-analysis persistence adapter (spec 002 §5)."""

from __future__ import annotations

import json

from ..contracts.documents import BlockSpan, CoverageUnit, Locator
from ..contracts.errors import DomainError
from ..media.models import MediaEvidence, MediaFact, MediaJob
from .sqlite import SqliteStore


class MediaStore:
    def __init__(self, db: SqliteStore) -> None:
        self.db = db

    def save_job(self, job: MediaJob) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO media_jobs (media_job_id, task_id, resource_id,
                artifact_id, filename, kind, media_type, size_bytes,
                duration_ms, input_snapshot, summary, limitations, coverage)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(media_job_id) DO UPDATE SET
                    artifact_id = excluded.artifact_id,
                    duration_ms = excluded.duration_ms,
                    summary = excluded.summary,
                    limitations = excluded.limitations,
                    coverage = excluded.coverage
                """,
                (
                    job.media_job_id,
                    job.task_id,
                    job.resource_id,
                    job.artifact_id,
                    job.filename,
                    job.kind,
                    job.media_type,
                    job.size_bytes,
                    job.duration_ms,
                    json.dumps(job.input_snapshot, ensure_ascii=False),
                    job.summary,
                    json.dumps(job.limitations, ensure_ascii=False),
                    json.dumps(
                        [c.model_dump(mode="json") for c in job.coverage],
                        ensure_ascii=False,
                    ),
                ),
            )

    def get_job(self, media_job_id: str) -> MediaJob:
        row = self.db.execute(
            "SELECT * FROM media_jobs WHERE media_job_id = ?",
            (media_job_id,),
        ).fetchone()
        if row is None:
            raise DomainError(
                "NOT_FOUND",
                f"media job not found: {media_job_id}",
                stage="storage",
            )
        return MediaJob(
            media_job_id=row["media_job_id"],
            task_id=row["task_id"],
            resource_id=row["resource_id"],
            artifact_id=row["artifact_id"],
            filename=row["filename"],
            kind=row["kind"],
            media_type=row["media_type"],
            size_bytes=row["size_bytes"],
            duration_ms=row["duration_ms"],
            input_snapshot=json.loads(row["input_snapshot"]),
            summary=row["summary"],
            limitations=json.loads(row["limitations"]),
            coverage=[
                CoverageUnit.model_validate(c)
                for c in json.loads(row["coverage"])
            ],
        )

    def get_by_task(self, task_id: str) -> MediaJob | None:
        row = self.db.execute(
            "SELECT media_job_id FROM media_jobs WHERE task_id = ?", (task_id,)
        ).fetchone()
        return self.get_job(row["media_job_id"]) if row else None

    def list(self) -> list[MediaJob]:
        rows = self.db.execute(
            "SELECT media_job_id FROM media_jobs ORDER BY media_job_id DESC"
        ).fetchall()
        return [self.get_job(r["media_job_id"]) for r in rows]

    def save_fact(self, fact: MediaFact) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO media_facts (fact_id, media_job_id, statement,
                segment_ids, verification_status) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    fact.fact_id,
                    fact.media_job_id,
                    fact.statement,
                    json.dumps(fact.segment_ids, ensure_ascii=False),
                    fact.verification_status,
                ),
            )

    def list_facts(self, media_job_id: str) -> list[MediaFact]:
        rows = self.db.execute(
            "SELECT * FROM media_facts WHERE media_job_id = ?"
            " ORDER BY fact_id",
            (media_job_id,),
        ).fetchall()
        return [
            MediaFact(
                fact_id=r["fact_id"],
                media_job_id=r["media_job_id"],
                statement=r["statement"],
                segment_ids=json.loads(r["segment_ids"]),
                verification_status=r["verification_status"],
            )
            for r in rows
        ]

    def save_evidence(self, evidence: MediaEvidence) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO media_evidence (evidence_id, media_job_id, fact_id,
                segment_id, artifact_id, block_span, locator, quote, relation)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence.evidence_id,
                    evidence.media_job_id,
                    evidence.fact_id,
                    evidence.segment_id,
                    evidence.artifact_id,
                    json.dumps(evidence.block_span.model_dump(mode="json")),
                    json.dumps(evidence.locator.model_dump(mode="json")),
                    evidence.quote,
                    evidence.relation,
                ),
            )

    def list_evidence(self, media_job_id: str) -> list[MediaEvidence]:
        rows = self.db.execute(
            "SELECT * FROM media_evidence WHERE media_job_id = ?"
            " ORDER BY evidence_id",
            (media_job_id,),
        ).fetchall()
        return [
            MediaEvidence(
                evidence_id=r["evidence_id"],
                media_job_id=r["media_job_id"],
                fact_id=r["fact_id"],
                segment_id=r["segment_id"],
                artifact_id=r["artifact_id"],
                block_span=BlockSpan.model_validate(
                    json.loads(r["block_span"])
                ),
                locator=Locator.model_validate(json.loads(r["locator"])),
                quote=r["quote"],
                relation=r["relation"],
            )
            for r in rows
        ]
