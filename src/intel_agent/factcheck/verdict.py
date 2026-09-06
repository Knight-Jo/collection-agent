"""Deterministic six-level verdict adjudication (spec 002 §4)."""

from __future__ import annotations

from .models import (
    EvidenceSufficiency,
    FactEvidence,
    Verdict,
)


def group_evidence(
    evidence: list[FactEvidence],
) -> dict[str, list[FactEvidence]]:
    """Group evidence by independence group; ungrouped evidence is isolated."""
    groups: dict[str, list[FactEvidence]] = {}
    for i, item in enumerate(evidence):
        key = item.independence_group or f"__ungrouped__{i}"
        groups.setdefault(key, []).append(item)
    return groups


def count_sources(evidence: list[FactEvidence]) -> dict:
    groups = group_evidence(evidence)
    independent = 0
    primary = 0
    for key, items in groups.items():
        if key.startswith("__ungrouped__"):
            # unknown independence does not count as confirmed independent
            continue
        independent += 1
        if any(i.source_nature == "primary" for i in items):
            primary += 1
    counter = sum(1 for i in evidence if i.relation == "contradicts")
    return {
        "independent_sources": independent,
        "primary_sources": primary,
        "counter_evidence": counter,
    }


def _sufficiency(counts: dict) -> EvidenceSufficiency:
    if counts["independent_sources"] >= 2 and counts["primary_sources"] >= 1:
        return "high"
    if counts["independent_sources"] >= 1:
        return "medium"
    return "low"


def adjudicate(
    evidence: list[FactEvidence],
) -> tuple[Verdict, EvidenceSufficiency, dict]:
    """Produce a verdict, sufficiency, and counts from validated evidence.

    This is a deterministic structural step: invalid citations must already be
    excluded by the caller. A model may supply the public rationale, but the
    six-level verdict and counts are derived here, not guessed by a model.
    """
    counts = count_sources(evidence)
    supports = [i for i in evidence if i.relation == "supports"]
    contradicts = [i for i in evidence if i.relation == "contradicts"]
    sufficiency = _sufficiency(counts)

    if not supports and not contradicts:
        verdict: Verdict = "insufficient"
    elif supports and not contradicts:
        verdict = "supported" if sufficiency == "high" else "mostly_supported"
    elif contradicts and not supports:
        verdict = "refuted" if sufficiency == "high" else "mostly_refuted"
    else:
        verdict = "disputed"

    return verdict, sufficiency, counts
