"""Bounded lexical retrieval over one task's committed research assets."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from .evidence import load_document, load_evidence
from .fact import load_fact
from .models import IntelError
from .search_queries import tokenize_query
from .state_store import StateStore
from .storage import verify_document_integrity, workspace_path
from .task import load_task
from .web.views import get_task_view

MAX_DOCUMENT_CHARS = 200_000
CHUNK_LINES = 12


class RetrievedPassage(BaseModel):
    """One server-validated passage available to the dialogue model."""

    id: str
    citation_kind: Literal["verified_evidence", "material_clue"]
    document_id: str
    evidence_id: str | None = None
    fact_id: str | None = None
    title: str
    source_url: str
    quote_text: str
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    source_content_hash: str
    score: int = Field(ge=0)


class TaskRetriever:
    """Retrieve only assets committed for one local research task."""

    def __init__(self, cwd: Path, store: StateStore):
        self.cwd = cwd
        self.store = store

    def seed_completed_task(self, task_id: str) -> None:
        """Expose the task's existing verified JSON assets once."""
        view = get_task_view(self.cwd, task_id)
        self.store.register_task(task_id)
        assets: set[tuple[Literal["document", "fact", "evidence"], str]] = {
            ("document", resource.document_id)
            for resource in view.resources
            if resource.document_id is not None
        }
        for question in view.questions:
            for fact in question.facts:
                assets.add(("fact", fact.id))
                for evidence in fact.evidence:
                    assets.add(("evidence", evidence.id))
                    assets.add(("document", evidence.document.id))
        self.store.seed_committed_assets(task_id, assets)

    def retrieve(
        self,
        task_id: str,
        query: str,
        *,
        limit: int = 8,
        snapshot: object | None = None,
    ) -> list[RetrievedPassage]:
        """Rank matching committed evidence and material text."""
        del snapshot  # Reserved for a precomputed task projection.
        if limit < 1:
            raise IntelError("INVALID_INPUT", "检索结果数量必须大于零")
        query_tokens = set(tokenize_query(query))
        if not query_tokens:
            return []

        task = load_task(self.cwd, task_id)
        questions = {question.id: question.text for question in task.questions}
        document_ids = self.store.committed_asset_ids(task_id, "document")
        fact_ids = self.store.committed_asset_ids(task_id, "fact")
        evidence_ids = self.store.committed_asset_ids(task_id, "evidence")
        passages: list[RetrievedPassage] = []

        for evidence_id in evidence_ids:
            evidence = load_evidence(self.cwd, evidence_id)
            if (
                evidence.task_id != task_id
                or evidence.fact_id not in fact_ids
                or evidence.document_id not in document_ids
            ):
                continue
            fact = load_fact(self.cwd, evidence.fact_id)
            document = load_document(self.cwd, evidence.document_id)
            haystack = "\n".join(
                (
                    questions.get(fact.question_id, ""),
                    fact.statement,
                    evidence.quote,
                    document.title,
                )
            )
            score = _overlap_score(query_tokens, haystack)
            if score:
                passages.append(
                    RetrievedPassage(
                        id=f"evidence:{evidence.id}",
                        citation_kind="verified_evidence",
                        document_id=document.id,
                        evidence_id=evidence.id,
                        fact_id=fact.id,
                        title=document.title,
                        source_url=document.final_url,
                        quote_text=evidence.quote,
                        line_start=evidence.line_start,
                        line_end=evidence.line_end,
                        source_content_hash=document.text_sha256,
                        score=score,
                    )
                )

        for document_id in document_ids:
            document = load_document(self.cwd, document_id)
            verify_document_integrity(self.cwd, document)
            if document.extraction_status != "complete":
                continue
            text_path = workspace_path(self.cwd, document.text_path)
            with text_path.open(encoding="utf-8") as source:
                lines = source.read(MAX_DOCUMENT_CHARS).splitlines()
            for offset in range(0, len(lines), CHUNK_LINES):
                chunk_lines = lines[offset : offset + CHUNK_LINES]
                quote = "\n".join(chunk_lines).strip()
                score = _overlap_score(
                    query_tokens, f"{document.title}\n{quote}"
                )
                if not quote or not score:
                    continue
                passages.append(
                    RetrievedPassage(
                        id=f"material:{document.id}:{offset + 1}",
                        citation_kind="material_clue",
                        document_id=document.id,
                        title=document.title,
                        source_url=document.final_url,
                        quote_text=quote,
                        line_start=offset + 1,
                        line_end=offset + len(chunk_lines),
                        source_content_hash=document.text_sha256,
                        score=score,
                    )
                )

        passages.sort(
            key=lambda item: (
                -item.score,
                item.citation_kind != "verified_evidence",
                item.id,
            )
        )
        return passages[:limit]


def _overlap_score(query_tokens: set[str], text: str) -> int:
    return len(query_tokens & set(tokenize_query(text)))
