"""Video extraction: subtitles, frame OCR (spec §8.7; ASR deferred)."""

from __future__ import annotations

from ..contracts.documents import CoverageUnit, ExtractResult, Locator
from .models import BackendRequest


def sample_times(
    duration_ms: int, interval_ms: int, max_frames: int
) -> list[int]:
    """Fixed-interval frame sample times, never past the media tail."""
    times = list(range(0, duration_ms, interval_ms))
    return times[:max_frames]


class VideoExtractor:
    """Aligns subtitle and frame evidence via the media and OCR backends."""

    def __init__(self, registry, resource_store, executor, config) -> None:
        self.registry = registry
        self.resource_store = resource_store
        self.executor = executor
        self.config = config

    def _backend(self, backend_id):
        return self.registry.get(backend_id)

    async def extract(self, resource, profile):
        from datetime import UTC, datetime

        from ..contracts.documents import BackendAttempt

        attempts: list[BackendAttempt] = []
        warnings: list[str] = []
        blocks = []
        coverage: list[CoverageUnit] = []

        def started(capability):
            return datetime.now(UTC)

        # Probe tracks and duration.
        probe_out, probe_attempt, _ = await self._run(
            "ffmpeg", resource.resource_id, "media_probe", profile
        )
        attempts.append(probe_attempt)
        if probe_out is None:
            return ExtractResult(
                resource_id=resource.resource_id,
                blocks=[],
                coverage=[],
                status="empty",
                attempts=attempts,
                warnings=["media probe failed"],
                extraction_profile_id=profile.id(),
            )
        duration_ms = probe_out.metrics.get("duration_ms", 0)
        has_subtitle = probe_out.metrics.get("has_subtitle", False)
        has_audio = probe_out.metrics.get("has_audio", False)
        coverage.extend(probe_out.coverage)

        # Subtitle path: preferred when a subtitle track exists.
        if has_subtitle:
            sub_out, sub_attempt, _ = await self._run(
                "ffmpeg", resource.resource_id, "subtitle_extract", profile
            )
            attempts.append(sub_attempt)
            if sub_out is not None:
                blocks.extend(sub_out.blocks)
                coverage.extend(sub_out.coverage)
            else:
                warnings.append("subtitle extraction failed")

        # ASR path: transcribe the audio track when there are no subtitles,
        # or when always_asr forces it.
        if (not has_subtitle or self.config.always_asr) and has_audio:
            if self.registry.available("whisper"):
                asr_out, asr_attempt, error = await self._run(
                    "whisper", resource.resource_id, "audio_asr", profile
                )
                attempts.append(asr_attempt)
                if asr_out is not None:
                    blocks.extend(asr_out.blocks)
                    coverage.extend(asr_out.coverage)
                else:
                    warnings.append(f"video ASR failed: {error}")
            else:
                warnings.append("video ASR not configured")

        # Frame OCR path (opt-in): sample frames and OCR on-screen text.
        if (
            self.config.video_frame_ocr
            and self.registry.available("tesseract")
            and duration_ms
        ):
            interval_ms = self.config.video_frame_interval_seconds * 1000
            times = sample_times(
                duration_ms, interval_ms, self.config.video_max_frames
            )
            for frame_ms in times:
                frame_out, frame_attempt, _ = await self._run(
                    "ffmpeg",
                    resource.resource_id,
                    "video_frame",
                    profile,
                    locator=Locator(frame_ms=frame_ms),
                )
                attempts.append(frame_attempt)
                if frame_out is None or not frame_out.derived_resources:
                    warnings.append(f"frame extraction failed at {frame_ms}")
                    continue
                frame_resource = frame_out.derived_resources[0]
                ocr_out, ocr_attempt, _ = await self._run(
                    "tesseract",
                    frame_resource.resource_id,
                    "ocr",
                    profile,
                    locator=Locator(frame_ms=frame_ms),
                )
                attempts.append(ocr_attempt)
                if ocr_out is not None:
                    blocks.extend(ocr_out.blocks)
            if len(times) < duration_ms // interval_ms + (
                1 if duration_ms % interval_ms else 0
            ):
                warnings.append("sampling truncated at max frames")

        status = "empty" if not blocks else "success"
        return ExtractResult(
            resource_id=resource.resource_id,
            blocks=blocks,
            coverage=coverage,
            status=status,
            attempts=attempts,
            warnings=warnings,
            extraction_profile_id=profile.id(),
        )

    async def _run(
        self, backend_id, resource_id, capability, profile, locator=None
    ):
        from datetime import UTC, datetime

        from ..contracts.documents import BackendAttempt

        backend = self._backend(backend_id)
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
            return None, attempt, None
        request = BackendRequest(
            resource_id=resource_id,
            capability=capability,
            locator=locator,
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
