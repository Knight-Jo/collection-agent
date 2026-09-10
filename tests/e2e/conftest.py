"""E2E harness: assemble the real engine against a temp data dir."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from intel_agent.context.manager import ContextManager
from intel_agent.context.retrieval import HybridRetriever, LexicalRetriever
from intel_agent.extraction.backends.asr import WhisperBackend
from intel_agent.extraction.backends.html import (
    BeautifulSoupBackend,
    TrafilaturaBackend,
)
from intel_agent.extraction.backends.media import FFmpegBackend
from intel_agent.extraction.backends.ocr import TesseractBackend
from intel_agent.extraction.backends.office import OfficeBackend
from intel_agent.extraction.backends.pdf import (
    PdfplumberBackend,
    PyMuPDFBackend,
)
from intel_agent.extraction.registry import BackendRegistry
from intel_agent.extraction.service import ExtractionService
from intel_agent.indexing.service import IndexingService
from intel_agent.indexing.tokenize import TiktokenCounter
from intel_agent.normalization import Normalizer
from intel_agent.runtime.config import (
    ContextConfig,
    ExtractionConfig,
    IndexingConfig,
)
from intel_agent.runtime.execution import Executor
from intel_agent.storage.materials import MaterialStore
from intel_agent.storage.resources import ResourceStore
from intel_agent.storage.tasks import TaskStore

SAMPLES = Path(__file__).resolve().parent.parent.parent / "samples"
MANIFEST = (
    Path(__file__).resolve().parent.parent / "fixtures" / "manifest.json"
)


class Harness:
    def __init__(self, *, import_roots, **services) -> None:
        self.import_roots = import_roots
        for name, value in services.items():
            setattr(self, name, value)


@pytest.fixture
def harness(tmp_path: Path):
    store = MaterialStore(tmp_path / "research.sqlite")
    task_store = TaskStore(store.db)
    resource_store = ResourceStore(
        tmp_path / "resources", [SAMPLES, tmp_path], store
    )
    executor = Executor(cpu_concurrency=2, gpu_concurrency=1)

    registry = BackendRegistry()
    registry.register("trafilatura", TrafilaturaBackend(resource_store))
    registry.register("beautifulsoup", BeautifulSoupBackend(resource_store))
    registry.register("pymupdf", PyMuPDFBackend(resource_store))
    registry.register("pdfplumber", PdfplumberBackend(resource_store))
    registry.register("tesseract", TesseractBackend(resource_store, executor))
    registry.register("office", OfficeBackend(resource_store))
    registry.register("ffmpeg", FFmpegBackend(resource_store, executor))
    registry.register(
        "whisper",
        WhisperBackend(
            resource_store,
            executor,
            model="small",
            device="cuda",
            compute_type="float16",
        ),
    )

    extraction = ExtractionService(
        registry, resource_store, executor, ExtractionConfig()
    )
    for profile in extraction.default_profiles():
        extraction.register_profile(profile)

    counter = TiktokenCounter()
    indexing = IndexingService(store, IndexingConfig(), counter)
    context = ContextManager(
        store,
        counter,
        ContextConfig(),
        hybrid=HybridRetriever(LexicalRetriever(store), None),
    )

    yield Harness(
        import_roots=[SAMPLES, tmp_path],
        store=store,
        task_store=task_store,
        resource_store=resource_store,
        extraction=extraction,
        indexing=indexing,
        context=context,
        normalizer=Normalizer(version="1"),
        executor=executor,
    )
    store.close()


def load_manifest() -> list[dict]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))["fixtures"]
