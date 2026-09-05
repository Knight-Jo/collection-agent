"""Audio extraction: probe metadata (spec §8.6; ASR deferred)."""

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
    """Probes audio tracks; transcription is a deferred ASR capability."""

    def __init__(self, registry, resource_store, executor, config) -> None:
        self.registry = registry
        self.resource_store = resource_store
        self.executor = executor
        self.config = config

    async def extract(self, resource, profile):
        from datetime import UTC, datetime

        from ..contracts.documents import (
            BackendAttempt,
            CoverageUnit,
            ExtractResult,
        )
        from .models import BackendRequest

        if not self.registry.available("ffmpeg"):
            return ExtractResult(
                resource_id=resource.resource_id,
                blocks=[],
                coverage=[],
                status="empty",
                warnings=["audio ASR requires a configured ASR backend"],
                extraction_profile_id=profile.id(),
            )
        backend = self.registry.get("ffmpeg")
        request = BackendRequest(
            resource_id=resource.resource_id,
            capability="media_probe",
            profile_id=profile.id(),
            remaining_seconds=self.config.resource_deadline_seconds,
        )
        started = datetime.now(UTC)
        try:
            output = await self.executor.run_backend(backend, request)
            attempt = BackendAttempt(
                backend_id="ffmpeg",
                backend_version=backend.version,
                capability="media_probe",
                started_at=started,
                ended_at=datetime.now(UTC),
                status="success",
            )
        except Exception as error:  # noqa: BLE001
            return ExtractResult(
                resource_id=resource.resource_id,
                blocks=[],
                coverage=[],
                status="empty",
                warnings=[f"audio probe failed: {error}"],
                extraction_profile_id=profile.id(),
            )
        return ExtractResult(
            resource_id=resource.resource_id,
            blocks=[],
            coverage=output.coverage
            or [
                CoverageUnit(
                    unit_type="time_range",
                    locator=Locator(),
                    status="success",
                )
            ],
            status="empty",
            attempts=[attempt],
            warnings=["audio transcription (ASR) not configured"],
            extraction_profile_id=profile.id(),
        )
