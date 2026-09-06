"""Real multi-format extraction verification over data/test_input_samples.

Runs the actual extraction backends (pymupdf, tesseract, office, ffmpeg,
whisper) against the checked-in sample files and asserts each produces at
least one text block. Fast formats (PDF/image/office) run by default; media
(whisper ASR) is gated behind RUN_MEDIA=1 because it is slow.
"""

from __future__ import annotations

import asyncio
import mimetypes
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from intel_agent.contracts.resources import ResourceOrigin
from intel_agent.extraction.backends.asr import WhisperBackend
from intel_agent.extraction.backends.media import FFmpegBackend
from intel_agent.extraction.backends.ocr import TesseractBackend
from intel_agent.extraction.backends.office import OfficeBackend
from intel_agent.extraction.backends.pdf import (
    PdfplumberBackend,
    PyMuPDFBackend,
)
from intel_agent.extraction.registry import BackendRegistry
from intel_agent.extraction.service import ExtractionService
from intel_agent.runtime.config import ResearchSettings
from intel_agent.runtime.execution import Executor
from intel_agent.storage.materials import MaterialStore
from intel_agent.storage.resources import ResourceStore

SAMPLE_DIR = (
    Path(__file__).resolve().parents[2] / "data" / "test_input_samples"
)

pytestmark = pytest.mark.skipif(
    not SAMPLE_DIR.is_dir(),
    reason="data/test_input_samples directory not present",
)

_MEDIA_PREFIXES = ("audio/", "video/")


def _required_backends(media_type: str) -> list[str]:
    if media_type == "application/pdf":
        return ["pymupdf"]
    if media_type.startswith("image/"):
        return ["tesseract"]
    if media_type.startswith(_MEDIA_PREFIXES):
        return ["ffmpeg", "whisper"]
    if "openxmlformats" in media_type:
        return ["office"]
    return []


def _samples() -> list[Path]:
    return sorted(p for p in SAMPLE_DIR.iterdir() if p.is_file())


@pytest.fixture(scope="session")
def extraction_stack(tmp_path_factory):
    settings = ResearchSettings()
    root = tmp_path_factory.mktemp("extract")
    store = MaterialStore(root / "store.sqlite")
    resource_store = ResourceStore(root / "resources", [], store)
    executor = Executor(cpu_concurrency=2, gpu_concurrency=1)
    registry = BackendRegistry()
    registry.register("pymupdf", PyMuPDFBackend(resource_store))
    registry.register("pdfplumber", PdfplumberBackend(resource_store))
    registry.register(
        "tesseract",
        TesseractBackend(
            resource_store, executor, settings.extraction.ocr_languages
        ),
    )
    registry.register("office", OfficeBackend(resource_store))
    registry.register("ffmpeg", FFmpegBackend(resource_store, executor))
    registry.register(
        "whisper",
        WhisperBackend(
            resource_store,
            executor,
            model=settings.extraction.whisper_model,
            device=settings.extraction.whisper_device,
            compute_type=settings.extraction.whisper_compute_type,
            language=settings.extraction.whisper_language,
            device_index=settings.extraction.whisper_device_index,
        ),
    )
    extraction = ExtractionService(
        registry, resource_store, executor, settings.extraction
    )
    for profile in extraction.default_profiles():
        extraction.register_profile(profile)
    yield resource_store, extraction, registry
    asyncio.run(executor.close())
    store.close()


@pytest.mark.parametrize("path", _samples(), ids=lambda p: p.name)
def test_sample_extracts_to_blocks(extraction_stack, path):
    resource_store, extraction, registry = extraction_stack
    media_type = (
        mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    )
    backends = _required_backends(media_type)
    if not backends:
        pytest.skip(f"no extraction backend for media type {media_type}")

    missing = [b for b in backends if not registry.available(b)]
    if missing:
        pytest.skip(f"backend(s) unavailable: {missing}")

    if media_type.startswith(_MEDIA_PREFIXES) and not os.environ.get(
        "RUN_MEDIA"
    ):
        pytest.skip("set RUN_MEDIA=1 to run slow whisper media extraction")

    data = path.read_bytes()

    async def chunks():
        for i in range(0, len(data), 65536):
            yield data[i : i + 65536]

    resource = asyncio.run(
        resource_store.write_stream(
            chunks(),
            origin=ResourceOrigin(
                local_display_name=path.name,
                acquired_at=datetime.now(UTC),
            ),
            media_type=media_type,
        )
    )
    profile_id = extraction.profile_for(resource.media_type)
    assert profile_id is not None, f"no profile for {resource.media_type}"

    result = asyncio.run(extraction.extract(resource, profile_id))
    assert result.blocks, (
        f"{path.name}: extraction produced no blocks "
        f"(status={result.status}, warnings={result.warnings})"
    )
