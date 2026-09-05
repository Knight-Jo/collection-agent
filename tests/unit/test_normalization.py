"""Normalization and chunking tests (T12)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from intel_agent.contracts.documents import (
    CoverageUnit,
    DocumentIdentity,
    EvidenceBlock,
    ExtractResult,
    Locator,
    NormalizationInput,
)
from intel_agent.indexing.chunking import chunk_document
from intel_agent.normalization import Normalizer


def _input(blocks=None, warnings=None):
    blocks = blocks or [
        EvidenceBlock(
            block_id="raw-1", text="第一段内容", block_type="paragraph",
            locator=Locator(page=1), origin_method="native_text",
            backend_id="pymupdf", backend_version="1.28",
        )
    ]
    result = ExtractResult(
        resource_id="r1",
        blocks=blocks,
        coverage=[
            CoverageUnit(unit_type="document", locator=Locator(),
                         status="success")
        ],
        status="success",
        warnings=warnings or [],
        extraction_profile_id="ep-1",
    )
    return NormalizationInput(
        result=result,
        resource_id="r1",
        identity=DocumentIdentity(document_id="d1", source_key="k"),
        revision_id="rev1",
    )


def test_attempt_timing_does_not_change_artifact():
    normalizer = Normalizer(version="1")
    original = normalizer.normalize(_input())
    retried = _input(warnings=["attempt_elapsed_ms=100"])
    assert normalizer.normalize(retried).artifact_id == original.artifact_id


def test_different_backend_version_changes_artifact():
    normalizer = Normalizer(version="1")
    a = normalizer.normalize(_input())
    b_input = _input(
        blocks=[
            EvidenceBlock(
                block_id="raw-1", text="第一段内容", block_type="paragraph",
                locator=Locator(page=1), origin_method="native_text",
                backend_id="pymupdf", backend_version="1.29",
            )
        ]
    )
    assert normalizer.normalize(b_input).artifact_id != a.artifact_id


def test_normalization_is_nfc_and_stable_blocks():
    normalizer = Normalizer(version="1")
    blocks = [
        EvidenceBlock(
            block_id="x", text="e\u0301tude", block_type="paragraph",
            locator=Locator(page=1), origin_method="native_text",
            backend_id="b", backend_version="1",
        )
    ]
    doc = normalizer.normalize(_input(blocks=blocks))
    assert doc.blocks[0].text == "étude"
    assert doc.blocks[0].block_id == "b1"


class _CharCounter:
    tokenizer_version = "test"

    def count(self, text: str) -> int:
        return len(text)


def test_chunk_spans_are_valid_and_within_block():
    normalizer = Normalizer(version="1")
    blocks = [
        EvidenceBlock(
            block_id="x", text="第一段" * 30, block_type="paragraph",
            locator=Locator(page=i), origin_method="native_text",
            backend_id="b", backend_version="1",
        )
        for i in range(1, 4)
    ]
    doc = normalizer.normalize(_input(blocks=blocks))
    chunks = chunk_document(
        doc, {"target_tokens": 40, "hard_limit_tokens": 120},
        _CharCounter(),
    )
    assert chunks
    seen = set()
    for chunk in chunks:
        assert chunk.chunk_id not in seen
        seen.add(chunk.chunk_id)
        for span in chunk.block_spans:
            assert 0 <= span.char_start < span.char_end
            assert span.char_end <= len(blocks[int(span.block_id[1:]) - 1].text)
