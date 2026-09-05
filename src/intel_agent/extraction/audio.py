"""Audio extraction: probe + ASR transcription (spec §8.6)."""

from __future__ import annotations

from datetime import UTC, datetime

from ..contracts.documents import (
    BackendAttempt,
    CoverageUnit,
    ExtractResult,
    Locator,
)
from .models import BackendRequest


def offset_locator(locator: Locator, offset_ms: int) -> Locator:
    """Shift a segment's media times to the original audio timeline."""
    shifted = locator.model_copy()
    if shifted.start_ms is not None:
        shifted.start_ms += offset_ms
    if shifted.end_ms is not None:
        shifted.end_ms += offset_ms
    return shifted


class AudioExtractor:
    """Probes an audio track and transcribes it with the ASR backend."""

    def __init__(self, registry, resource_store, executor, config) -> None:
        self.registry = registry
        self.resource_store = resource_store
        self.executor = executor
        self.config = config

    async def extract(self, resource, profile):
        attempts: list[BackendAttempt] = []
        warnings: list[str] = []

        # Probe duration/tracks.
        if self.registry.available("ffmpeg"):
            probe_out, probe_attempt, _ = await self._run(
                "ffmpeg", resource.resource_id, "media_probe", profile
            )
            attempts.append(probe_attempt)
            coverage = probe_out.coverage if probe_out else []
        else:
            coverage = []
            warnings.append("media probe backend unavailable")

        # Transcribe via whisper.
        if self.registry.available("whisper"):
            asr_out, asr_attempt, error = await self._run(
                "whisper", resource.resource_id, "audio_asr", profile
            )
            attempts.append(asr_attempt)
            if asr_out is not None:
                blocks = asr_out.blocks
                coverage.extend(asr_out.coverage)
            else:
                blocks = []
                warnings.append(f"audio transcription failed: {error}")
        else:
            blocks = []
            warnings.append("audio transcription (ASR) not configured")

        status = "empty" if not blocks else "success"
        return ExtractResult(
            resource_id=resource.resource_id,
            blocks=blocks,
            coverage=coverage
            or [
                CoverageUnit(
                    unit_type="time_range",
                    locator=Locator(),
                    status="success",
                )
            ],
            status=status,
            attempts=attempts,
            warnings=warnings,
            extraction_profile_id=profile.id(),
        )

    async def _run(self, backend_id, resource_id, capability, profile):
        backend = self.registry.get(backend_id)
        if backend.availability() != "available":
            attempt = BackendAttempt(
                backend_id=backend_id,
                backend_version=backend.version,
                capability=capability,
                started_at=datetime.now(UTC),
                ended_at=datetime.now(UTC),
                status="failed",
                error="unavailable",
            )
            return None, attempt, "unavailable"
        request = BackendRequest(
            resource_id=resource_id,
            capability=capability,
            profile_id=profile.id(),
            remaining_seconds=self.config.resource_deadline_seconds,
        )
        started = datetime.now(UTC)
        try:
            output = await self.executor.run_backend(
                backend, request, gpu=(capability == "audio_asr")
            )
            return (
                output,
                BackendAttempt(
                    backend_id=backend_id,
                    backend_version=backend.version,
                    capability=capability,
                    started_at=started,
                    ended_at=datetime.now(UTC),
                    status="success",
                ),
                None,
            )
        except Exception as error:  # noqa: BLE001
            return (
                None,
                BackendAttempt(
                    backend_id=backend_id,
                    backend_version=backend.version,
                    capability=capability,
                    started_at=started,
                    ended_at=datetime.now(UTC),
                    status="failed",
                    error=str(error),
                ),
                str(error),
            )
