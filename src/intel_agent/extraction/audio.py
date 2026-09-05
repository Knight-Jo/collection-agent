"""Audio extraction: probe, segment, transcribe (spec §8.6)."""

from __future__ import annotations

from ..contracts.documents import Locator


def offset_locator(locator: Locator, offset_ms: int) -> Locator:
    """Shift a segment's media times to the original audio timeline."""
    shifted = locator.model_copy()
    if shifted.start_ms is not None:
        shifted.start_ms += offset_ms
    if shifted.end_ms is not None:
        shifted.end_ms += offset_ms
    return shifted


class AudioExtractor:
    """Transcribes audio via injected media and ASR backends."""

    def __init__(self, registry, resource_store, executor, config) -> None:
        self.registry = registry
        self.resource_store = resource_store
        self.executor = executor
        self.config = config

    async def extract(self, resource, profile):
        # Deferred: probe the track, segment into ~30s windows, and run the
        # ASR backend per segment with original-timeline offsets.
        from ..contracts.documents import CoverageUnit, ExtractResult

        return ExtractResult(
            resource_id=resource.resource_id,
            blocks=[],
            coverage=[
                CoverageUnit(
                    unit_type="document",
                    locator=Locator(),
                    status="skipped",
                    reason="audio ASR backend not configured",
                )
            ],
            status="empty",
            warnings=["audio ASR requires a configured ASR backend"],
            extraction_profile_id=profile.id(),
        )
