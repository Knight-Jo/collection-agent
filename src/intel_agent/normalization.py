"""Pure normalization of extraction results into versioned documents."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Any

from .contracts.documents import (
    EvidenceBlock,
    NormalizationInput,
    NormalizedDocument,
)
from .storage._ids import artifact_id


def _normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    return normalized


def _normalize_metadata(metadata: Any) -> Any:
    if isinstance(metadata, dict):
        return {k: _normalize_metadata(v) for k, v in metadata.items()}
    if isinstance(metadata, list):
        return [_normalize_metadata(v) for v in metadata]
    if isinstance(metadata, str):
        return _normalize_text(metadata)
    return metadata


def artifact_manifest(document: NormalizedDocument) -> dict[str, Any]:
    """Stable semantic manifest: ordered blocks, locators, coverage.

    Excludes attempts, warnings, and timing so retries of identical content
    produce the same artifact identity (spec §4.4).
    """
    return {
        "title": document.title,
        "published_at": (
            document.published_at.isoformat()
            if document.published_at
            else None
        ),
        "language": document.language,
        "extraction_profile_id": document.extraction_profile_id,
        "blocks": [
            {
                "text": block.text,
                "block_type": block.block_type,
                "locator": block.locator.model_dump(mode="json"),
                "origin_method": block.origin_method,
                "backend_id": block.backend_id,
                "backend_version": block.backend_version,
            }
            for block in document.blocks
        ],
        "coverage": [c.model_dump(mode="json") for c in document.coverage],
    }


def manifest_hash(document: NormalizedDocument) -> str:
    payload = json.dumps(
        artifact_manifest(document),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class Normalizer:
    """Pure transformer; never summarizes or drops evidence (spec §9.1)."""

    def __init__(self, version: str = "1") -> None:
        self.version = version

    def normalize(self, input_: NormalizationInput) -> NormalizedDocument:
        blocks: list[EvidenceBlock] = []
        for ordinal, block in enumerate(input_.result.blocks, start=1):
            blocks.append(
                EvidenceBlock(
                    block_id=f"b{ordinal}",
                    text=_normalize_text(block.text),
                    block_type=block.block_type,
                    locator=block.locator,
                    origin_method=block.origin_method,
                    backend_id=block.backend_id,
                    backend_version=block.backend_version,
                    confidence=block.confidence,
                    metadata=_normalize_metadata(block.metadata),
                )
            )
        status = (
            "empty"
            if not blocks
            else "partial"
            if input_.result.status in ("partial", "empty")
            and input_.result.coverage
            else input_.result.status
        )
        document = NormalizedDocument(
            document_id=input_.identity.document_id,
            revision_id=input_.revision_id,
            artifact_id="",
            resource_id=input_.resource_id,
            title=_normalize_text(input_.result.title)
            if input_.result.title
            else None,
            published_at=input_.published_at,
            language=input_.language,
            blocks=blocks,
            coverage=input_.result.coverage,
            attempts=input_.result.attempts,
            warnings=input_.result.warnings,
            provenance=input_.provenance,
            extraction_profile_id=input_.result.extraction_profile_id,
            normalizer_version=self.version,
            status=status,
        )
        document.artifact_id = artifact_id(
            document.revision_id,
            document.extraction_profile_id,
            document.normalizer_version,
            manifest_hash(document),
        )
        return document
