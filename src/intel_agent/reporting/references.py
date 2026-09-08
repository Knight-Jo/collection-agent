"""Reference-list extraction for report exports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ExportMeta:
    """Document-header metadata shared by every export format."""

    subject: str
    generated_at: datetime


@dataclass(frozen=True)
class Reference:
    index: int
    title: str
    url: str


def references_from_evidence(evidence: dict | None) -> list[Reference]:
    """Deduplicated, claim-order-preserving source list.

    The stored evidence review carries per-claim source metadata (title +
    resolved URL); several claims usually share a source, so identity is the
    URL when present and the title otherwise.
    """
    if not evidence:
        return []
    seen: set[str] = set()
    references: list[Reference] = []
    for claim in evidence.get("claims", []):
        url = str(claim.get("source_url") or "").strip()
        title = str(claim.get("source_title") or "").strip()
        if not url and not title:
            continue
        key = url or title
        if key in seen:
            continue
        seen.add(key)
        references.append(
            Reference(index=len(references) + 1, title=title, url=url)
        )
    return references
