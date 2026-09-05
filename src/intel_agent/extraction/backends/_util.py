"""Block construction helpers shared by backends."""

from __future__ import annotations

from ...contracts.documents import EvidenceBlock, Locator, OriginMethod
from ..models import Capability


def make_block(
    backend_id: str,
    version: str,
    ordinal: int,
    text: str,
    block_type: str,
    *,
    locator: Locator | None = None,
    origin_method: OriginMethod = "native_text",
    confidence: float | None = None,
    metadata: dict | None = None,
) -> EvidenceBlock:
    return EvidenceBlock(
        block_id=f"{backend_id}-{ordinal}",
        text=text,
        block_type=block_type,
        locator=locator or Locator(),
        origin_method=origin_method,
        backend_id=backend_id,
        backend_version=version,
        confidence=confidence,
        metadata=metadata or {},
    )
