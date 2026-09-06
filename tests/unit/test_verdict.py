"""Fact-check verdict adjudication tests (spec 002 US3)."""

from __future__ import annotations

from intel_agent.contracts.documents import Citation
from intel_agent.factcheck.models import FactEvidence, SourceNature
from intel_agent.factcheck.verdict import adjudicate


def _evidence(
    relation, group=None, nature: SourceNature = "unknown"
) -> FactEvidence:
    return FactEvidence(
        evidence_id=relation + (group or ""),
        fact_check_id="fc1",
        relation=relation,
        quote="q",
        citation=Citation(
            citation_id="C1",
            chunk_id="c",
            artifact_id="a",
            document_id="d",
            revision_id="r",
            resource_id="res",
        ),
        independence_group=group,
        source_nature=nature,
    )


def test_no_evidence_is_insufficient():
    verdict, sufficiency, counts = adjudicate([])
    assert verdict == "insufficient"
    assert sufficiency == "low"
    assert counts["independent_sources"] == 0


def test_supported_with_two_independent_primary_sources():
    evidence = [
        _evidence("supports", "g1", "primary"),
        _evidence("supports", "g2", "primary"),
    ]
    verdict, sufficiency, counts = adjudicate(evidence)
    assert verdict == "supported"
    assert sufficiency == "high"
    assert counts["independent_sources"] == 2
    assert counts["primary_sources"] == 2


def test_contradicts_without_supports_is_refuted():
    evidence = [
        _evidence("contradicts", "g1", "primary"),
        _evidence("contradicts", "g2", "primary"),
    ]
    verdict, _, _ = adjudicate(evidence)
    assert verdict == "refuted"


def test_support_and_contradiction_is_disputed():
    evidence = [
        _evidence("supports", "g1", "primary"),
        _evidence("contradicts", "g2", "primary"),
    ]
    verdict, _, _ = adjudicate(evidence)
    assert verdict == "disputed"


def test_ungrouped_evidence_does_not_count_independent():
    evidence = [_evidence("supports"), _evidence("supports")]
    _, _, counts = adjudicate(evidence)
    assert counts["independent_sources"] == 0
    assert counts["primary_sources"] == 0
