"""Video extraction: subtitles, ASR, and frame OCR (spec §8.7)."""

from __future__ import annotations

from ..contracts.documents import Locator


def sample_times(
    duration_ms: int, interval_ms: int, max_frames: int
) -> list[int]:
    """Fixed-interval frame sample times, never past the media tail."""
    times = list(range(0, duration_ms, interval_ms))
    return times[:max_frames]


class VideoExtractor:
    """Aligns subtitle, speech, and frame evidence via injected backends."""

    def __init__(self, registry, resource_store, executor, config) -> None:
        self.registry = registry
        self.resource_store = resource_store
        self.executor = executor
        self.config = config

    async def extract(self, resource, profile):
        from ..contracts.documents import CoverageUnit, ExtractResult

        return ExtractResult(
            resource_id=resource.resource_id,
            blocks=[],
            coverage=[
                CoverageUnit(
                    unit_type="document",
                    locator=Locator(),
                    status="skipped",
                    reason="video media backend not configured",
                )
            ],
            status="empty",
            warnings=["video extraction requires a configured media backend"],
            extraction_profile_id=profile.id(),
        )
