"""Fact-check persistence adapter (spec 002 §4)."""

from __future__ import annotations

import json

from ..contracts.documents import Citation
from ..contracts.errors import DomainError
from ..factcheck.models import FactCheck, FactEvidence
from .sqlite import SqliteStore


class FactCheckStore:
    def __init__(self, db: SqliteStore) -> None:
        self.db = db

    def save(self, fact_check: FactCheck) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO fact_checks (fact_check_id, task_id, claim,
                input_snapshot, understanding, questions, checkability,
                checkability_reason, verdict, evidence_sufficiency, rationale,
                limitations, independent_sources, primary_sources,
                counter_evidence)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(fact_check_id) DO UPDATE SET
                    understanding = excluded.understanding,
                    questions = excluded.questions,
                    checkability = excluded.checkability,
                    checkability_reason = excluded.checkability_reason,
                    verdict = excluded.verdict,
                    evidence_sufficiency = excluded.evidence_sufficiency,
                    rationale = excluded.rationale,
                    limitations = excluded.limitations,
                    independent_sources = excluded.independent_sources,
                    primary_sources = excluded.primary_sources,
                    counter_evidence = excluded.counter_evidence
                """,
                (
                    fact_check.fact_check_id,
                    fact_check.task_id,
                    fact_check.claim,
                    json.dumps(fact_check.input_snapshot, ensure_ascii=False),
                    fact_check.understanding,
                    json.dumps(fact_check.questions, ensure_ascii=False),
                    fact_check.checkability,
                    fact_check.checkability_reason,
                    fact_check.verdict,
                    fact_check.evidence_sufficiency,
                    fact_check.rationale,
                    json.dumps(fact_check.limitations, ensure_ascii=False),
                    fact_check.independent_sources,
                    fact_check.primary_sources,
                    fact_check.counter_evidence,
                ),
            )

    def get(self, fact_check_id: str) -> FactCheck:
        row = self.db.execute(
            "SELECT * FROM fact_checks WHERE fact_check_id = ?",
            (fact_check_id,),
        ).fetchone()
        if row is None:
            raise DomainError(
                "NOT_FOUND",
                f"fact check not found: {fact_check_id}",
                stage="storage",
            )
        return self._fact_check_from_row(row)

    def get_by_task(self, task_id: str) -> FactCheck | None:
        row = self.db.execute(
            "SELECT fact_check_id FROM fact_checks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        return self.get(row["fact_check_id"]) if row else None

    def list(self) -> list[FactCheck]:
        rows = self.db.execute(
            "SELECT fact_check_id FROM fact_checks ORDER BY fact_check_id DESC"
        ).fetchall()
        return [self.get(r["fact_check_id"]) for r in rows]

    @staticmethod
    def _fact_check_from_row(row) -> FactCheck:
        return FactCheck(
            fact_check_id=row["fact_check_id"],
            task_id=row["task_id"],
            claim=row["claim"],
            input_snapshot=json.loads(row["input_snapshot"]),
            understanding=row["understanding"],
            questions=json.loads(row["questions"]),
            checkability=row["checkability"],
            checkability_reason=row["checkability_reason"],
            verdict=row["verdict"],
            evidence_sufficiency=row["evidence_sufficiency"],
            rationale=row["rationale"],
            limitations=json.loads(row["limitations"]),
            independent_sources=row["independent_sources"],
            primary_sources=row["primary_sources"],
            counter_evidence=row["counter_evidence"],
        )

    def save_evidence(self, evidence: FactEvidence) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO fact_evidence (evidence_id, fact_check_id,
                relation, quote, citation, publisher_key, independence_group,
                source_nature, attribution_basis, source_title)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence.evidence_id,
                    evidence.fact_check_id,
                    evidence.relation,
                    evidence.quote,
                    json.dumps(
                        evidence.citation.model_dump(mode="json"),
                        ensure_ascii=False,
                    ),
                    evidence.publisher_key,
                    evidence.independence_group,
                    evidence.source_nature,
                    evidence.attribution_basis,
                    evidence.source_title,
                ),
            )

    def list_evidence(self, fact_check_id: str) -> list[FactEvidence]:
        rows = self.db.execute(
            "SELECT * FROM fact_evidence WHERE fact_check_id = ?"
            " ORDER BY evidence_id",
            (fact_check_id,),
        ).fetchall()
        return [
            FactEvidence(
                evidence_id=r["evidence_id"],
                fact_check_id=r["fact_check_id"],
                relation=r["relation"],
                quote=r["quote"],
                citation=Citation.model_validate(json.loads(r["citation"])),
                publisher_key=r["publisher_key"],
                independence_group=r["independence_group"],
                source_nature=r["source_nature"],
                attribution_basis=r["attribution_basis"],
                source_title=r["source_title"],
            )
            for r in rows
        ]
