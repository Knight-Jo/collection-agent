"""FFmpeg/FFprobe media backend (spec §8.6, §8.7)."""

from __future__ import annotations

import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

from ...contracts.documents import CoverageUnit, Locator
from ...contracts.errors import DomainError
from ...contracts.resources import ResourceOrigin
from ...runtime.execution import Executor
from ..models import Availability, BackendOutput, BackendRequest
from ._base import BaseBackend
from ._util import make_block

_SRT_TIME = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})[.,](\d{1,3})")


def _srt_to_ms(value: str) -> int:
    match = _SRT_TIME.match(value.strip())
    if not match:
        return 0
    h, m, s, ms = (int(g) for g in match.groups())
    return h * 3_600_000 + m * 60_000 + s * 1000 + ms


class FFmpegBackend(BaseBackend):
    backend_id = "ffmpeg"
    version = "7"
    capabilities = ("media_probe", "subtitle_extract", "video_frame")
    media_types = ("audio/mpeg", "audio/wav", "video/mp4", "video/webm")

    def __init__(self, resource_store, executor: Executor) -> None:
        super().__init__(resource_store)
        self.executor = executor

    def availability(self) -> Availability:
        if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
            return "missing_dependency"
        return "available"

    async def run(self, request: BackendRequest) -> BackendOutput:
        path = self.blob_path(request.resource_id)
        if request.capability == "media_probe":
            return await self._probe(path, request)
        if request.capability == "subtitle_extract":
            return await self._subtitles(path, request)
        if request.capability == "video_frame":
            return await self._frame(path, request)
        return BackendOutput(warnings=["unsupported capability"])

    async def _probe(self, path: Path, request) -> BackendOutput:
        result = await self.executor.run_process(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(path),
            ],
            timeout_seconds=request.remaining_seconds,
        )
        if result.returncode != 0:
            raise DomainError(
                "EXTRACTION_FAILED",
                "ffprobe failed",
                stage="extraction",
                safe_details={"stderr": result.stderr.decode()[:200]},
            )
        data = json.loads(result.stdout.decode("utf-8", errors="replace"))
        duration_ms = int(
            float(data.get("format", {}).get("duration", 0)) * 1000
        )
        streams = data.get("streams", [])
        subtitle = any(s.get("codec_type") == "subtitle" for s in streams)
        audio = any(s.get("codec_type") == "audio" for s in streams)
        return BackendOutput(
            coverage=[
                CoverageUnit(
                    unit_type="time_range",
                    locator=Locator(start_ms=0, end_ms=duration_ms),
                    status="success" if duration_ms else "empty",
                )
            ],
            metrics={
                "duration_ms": duration_ms,
                "has_subtitle": subtitle,
                "has_audio": audio,
                "streams": len(streams),
            },
        )

    async def _subtitles(self, path: Path, request) -> BackendOutput:
        result = await self.executor.run_process(
            ["ffmpeg", "-i", str(path), "-map", "0:s:0", "-f", "srt", "-"],
            timeout_seconds=request.remaining_seconds,
        )
        if result.returncode != 0 or not result.stdout:
            return BackendOutput(
                coverage=[
                    CoverageUnit(
                        unit_type="time_range",
                        locator=Locator(),
                        status="empty",
                        reason="no subtitle stream",
                    )
                ],
                warnings=["no subtitle stream"],
            )
        text = result.stdout.decode("utf-8", errors="replace")
        blocks = []
        ordinal = 1
        for block in text.split("\n\n"):
            lines = block.strip().split("\n")
            if len(lines) < 3 or "-->" not in lines[1]:
                continue
            start_raw, end_raw = lines[1].split("-->")
            content = " ".join(lines[2:]).strip()
            if not content:
                continue
            blocks.append(
                make_block(
                    self.backend_id,
                    self.version,
                    ordinal,
                    content,
                    "subtitle",
                    locator=Locator(
                        start_ms=_srt_to_ms(start_raw),
                        end_ms=_srt_to_ms(end_raw),
                    ),
                    origin_method="subtitle",
                )
            )
            ordinal += 1
        status = "success" if blocks else "empty"
        return BackendOutput(
            blocks=blocks,
            coverage=[
                CoverageUnit(
                    unit_type="time_range",
                    locator=Locator(),
                    status=status,
                )
            ],
        )

    async def _frame(self, path: Path, request) -> BackendOutput:
        frame_ms = (request.locator or Locator()).frame_ms or 0
        seconds = frame_ms / 1000.0
        out = path.parent / f"frame-{frame_ms}.png"
        result = await self.executor.run_process(
            [
                "ffmpeg",
                "-ss",
                f"{seconds:.3f}",
                "-i",
                str(path),
                "-frames:v",
                "1",
                "-y",
                str(out),
            ],
            timeout_seconds=request.remaining_seconds,
        )
        if result.returncode != 0 or not out.exists():
            return BackendOutput(
                warnings=[f"frame extract failed: {frame_ms}"]
            )

        async def chunks():
            with out.open("rb") as fh:
                while chunk := fh.read(64 * 1024):
                    yield chunk

        derived = await self.resource_store.write_stream(
            chunks(),
            origin=ResourceOrigin(
                local_display_name=out.name,
                acquired_at=datetime.now(UTC),
            ),
            media_type="image/png",
            parent_resource_id=request.resource_id,
            transform={"frame_ms": frame_ms},
        )
        out.unlink(missing_ok=True)
        return BackendOutput(derived_resources=[derived])
