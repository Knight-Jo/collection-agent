"""Context formatting and citations (spec §11)."""

from __future__ import annotations

from ..contracts.documents import Chunk, Citation
from ..contracts.errors import DomainError
from ..contracts.research import ContextPackage


def build_citations(
    chunks: list[Chunk], source_by_artifact: dict[str, str]
) -> list[Citation]:
    citations: list[Citation] = []
    for i, chunk in enumerate(chunks):
        citations.append(
            Citation(
                citation_id=f"C{i + 1}",
                chunk_id=chunk.chunk_id,
                artifact_id=chunk.artifact_id,
                document_id=chunk.document_id,
                revision_id=chunk.revision_id,
                source_url=source_by_artifact.get(chunk.artifact_id),
                resource_id="",
                locators=chunk.locators,
                block_spans=chunk.block_spans,
            )
        )
    return citations


def format_context(
    chunks: list[Chunk], citations: list[Citation]
) -> str:
    parts: list[str] = []
    for chunk, citation in zip(chunks, citations, strict=True):
        header = f"[{citation.citation_id}]"
        if citation.source_url:
            header += f" {citation.source_url}"
        parts.append(f"{header}\n{chunk.text}")
    return "\n\n".join(parts)


def validate_citation_ids(ids: list[str], package: ContextPackage) -> None:
    known = {c.citation_id for c in package.citations}
    unknown = [i for i in ids if i not in known]
    if unknown:
        raise DomainError(
            "INVALID_DECISION",
            f"unknown citation ids: {unknown}",
            stage="context",
        )
