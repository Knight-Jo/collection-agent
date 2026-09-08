"""Reference-list extraction for report exports.

Report bodies cite sources with inline markers like ``[C1]``; the appendix
must be keyed the same way or the markers point nowhere. Keys come from
``report.citation_ids`` (cited first, in order) plus any remaining evidence
claim ids, so every marker in the body resolves to exactly one entry.
"""

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
    """One appendix entry, keyed by the citation id the body uses."""

    key: str
    title: str
    url: str


def references_for_report(report, evidence: dict | None) -> list[Reference]:
    """Citation-keyed reference list for a report.

    Resolution order: the ids the report actually cites (``citation_ids``),
    then evidence-claim ids not cited (covers reports whose writer omitted
    the id list while still marking the body). Ids that no stored evidence
    claim resolves keep a placeholder entry rather than silently vanishing:
    a dangling ``[C3]`` marker must still land somewhere honest.
    """
    by_id = _sources_by_citation_id(evidence)
    ordered: list[str] = []
    for citation_id in list(getattr(report, "citation_ids", []) or []):
        if citation_id and citation_id not in ordered:
            ordered.append(citation_id)
    for citation_id in by_id:
        if citation_id not in ordered:
            ordered.append(citation_id)
    return [
        Reference(
            key=citation_id,
            title=by_id.get(citation_id, ("", ""))[0] or "（来源信息缺失）",
            url=by_id.get(citation_id, ("", ""))[1],
        )
        for citation_id in ordered
    ]


def references_from_evidence(evidence: dict | None) -> list[Reference]:
    """Deduplicated, claim-order-preserving source list (legacy ordering)."""
    seen: set[str] = set()
    references: list[Reference] = []
    for claim in (evidence or {}).get("claims", []):
        url = str(claim.get("source_url") or "").strip()
        title = str(claim.get("source_title") or "").strip()
        citation_id = str(claim.get("citation_id") or "").strip()
        if not url and not title:
            continue
        key = url or title
        if key in seen:
            continue
        seen.add(key)
        references.append(
            Reference(
                key=citation_id or str(len(references) + 1),
                title=title,
                url=url,
            )
        )
    return references


def _sources_by_citation_id(
    evidence: dict | None,
) -> dict[str, tuple[str, str]]:
    """citation_id -> (title, url), first claim wins on duplicates."""
    resolved: dict[str, tuple[str, str]] = {}
    for claim in (evidence or {}).get("claims", []):
        citation_id = str(claim.get("citation_id") or "").strip()
        if not citation_id or citation_id in resolved:
            continue
        resolved[citation_id] = (
            str(claim.get("source_title") or "").strip(),
            str(claim.get("source_url") or "").strip(),
        )
    return resolved
