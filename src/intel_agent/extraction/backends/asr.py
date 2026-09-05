"""faster-whisper ASR backend (spec §8.6, §8.7)."""

from __future__ import annotations

import asyncio

from ...contracts.documents import CoverageUnit, Locator
from ..models import Availability, BackendOutput, BackendRequest
from ._base import BaseBackend
from ._util import make_block


class WhisperBackend(BaseBackend):
    backend_id = "whisper"
    capabilities = ("audio_asr",)
    media_types = (
        "audio/mpeg",
        "audio/mp4",
        "audio/wav",
        "audio/x-m4a",
        "video/mp4",
        "video/webm",
    )

    def __init__(
        self,
        resource_store,
        executor,
        *,
        model: str = "small",
        device: str = "cuda",
        compute_type: str = "float16",
        language: str | None = None,
        device_index: int = 0,
    ) -> None:
        super().__init__(resource_store)
        self.executor = executor
        self.model_name = model
        self.version = model
        self.device = device
        self.compute_type = compute_type
        self.language = language
        self.device_index = device_index
        self._model = None

    def availability(self) -> Availability:
        try:
            import faster_whisper  # noqa: F401
        except ImportError:
            return "missing_dependency"
        if self.device.startswith("cuda"):
            try:
                import ctranslate2

                if ctranslate2.get_cuda_device_count() == 0:
                    return "missing_dependency"
            except ImportError:
                return "missing_dependency"
        return "available"

    def _load_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(
                self.model_name,
                device=self.device,
                compute_type=self.compute_type,
                device_index=self.device_index,
            )
        return self._model

    def _transcribe_sync(self, path) -> tuple[list[tuple[int, int, str]], str]:
        model = self._load_model()
        segments, info = model.transcribe(
            str(path),
            language=self.language,
            vad_filter=True,
            beam_size=5,
        )
        results: list[tuple[int, int, str]] = []
        for segment in segments:
            text = segment.text.strip()
            if text:
                results.append(
                    (
                        int(segment.start * 1000),
                        int(segment.end * 1000),
                        text,
                    )
                )
        return results, getattr(info, "language", "")

    async def run(self, request: BackendRequest) -> BackendOutput:
        path = self.blob_path(request.resource_id)
        results, lang = await asyncio.to_thread(self._transcribe_sync, path)
        blocks = []
        for ordinal, (start_ms, end_ms, text) in enumerate(results, start=1):
            blocks.append(
                make_block(
                    self.backend_id,
                    self.version,
                    ordinal,
                    text,
                    "paragraph",
                    locator=Locator(start_ms=start_ms, end_ms=end_ms),
                    origin_method="asr",
                    metadata={"language": lang or None},
                )
            )
        status = "success" if blocks else "empty"
        return BackendOutput(
            blocks=blocks,
            coverage=[
                CoverageUnit(
                    unit_type="time_range", locator=Locator(), status=status
                )
            ],
            metrics={"language": lang, "model": self.model_name},
        )
