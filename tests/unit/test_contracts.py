"""Contract model validation tests (T01)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from intel_agent.contracts.documents import (
    BlockSpan,
    Locator,
    NormalizationInput,
)
from intel_agent.contracts.research import (
    ResearchDecision,
    SearchOccurrence,
    SearchQuery,
)


def test_invalid_locations_and_decisions_are_rejected():
    for fields in (
        {"page": 0},
        {"start_ms": 20, "end_ms": 10},
        {"bbox": (0.8, 0.0, 0.2, 1.0)},
    ):
        with pytest.raises(ValidationError):
            Locator.model_validate(fields)
    with pytest.raises(ValidationError):
        ResearchDecision(
            action="search",
            queries=[],
            source_types=["web"],
            evidence_gaps=[],
            reason="Need evidence",
        )


def test_finish_decision_requires_answer_and_no_queries():
    with pytest.raises(ValidationError):
        ResearchDecision(
            action="finish",
            queries=[],
            source_types=[],
            evidence_gaps=[],
            reason="done",
        )
    with pytest.raises(ValidationError):
        ResearchDecision(
            action="finish",
            queries=[SearchQuery(text="x")],
            source_types=[],
            evidence_gaps=[],
            reason="done",
            draft_answer="an answer",
        )


def test_naive_datetimes_are_rejected():
    from intel_agent.contracts.resources import ResourceOrigin

    with pytest.raises(ValidationError):
        ResourceOrigin(acquired_at=datetime(2026, 1, 1))


def test_valid_locator_and_bbox():
    locator = Locator(
        page=1, start_ms=500, end_ms=1500, bbox=(0.0, 0.0, 0.5, 0.5)
    )
    assert locator.page == 1
    assert locator.start_ms == 500


def test_block_span_half_open_and_ordered():
    assert BlockSpan(block_id="b", char_start=0, char_end=5).char_end == 5
    with pytest.raises(ValidationError):
        BlockSpan(block_id="b", char_start=5, char_end=5)


def test_provenance_resolves_to_search_occurrence():
    occ = SearchOccurrence(
        provider="searxng",
        query_id="q1",
        observed_at=datetime.now(UTC),
        original_url="https://example.org/a",
        channel="web",
    )
    payload = NormalizationInput.model_validate(
        {
            "result": {
                "resource_id": "r1",
                "blocks": [],
                "coverage": [],
                "status": "empty",
                "extraction_profile_id": "e1",
            },
            "resource_id": "r1",
            "identity": {"document_id": "d1", "source_key": "k"},
            "revision_id": "rev1",
            "provenance": [occ],
        }
    )
    assert isinstance(payload.provenance[0], SearchOccurrence)
