"""PDF extraction backend tests (T08)."""

from __future__ import annotations

import io
from datetime import UTC, datetime

import pytest

from intel_agent.contracts.resources import ResourceOrigin
from intel_agent.extraction.backends.pdf import (
    PdfplumberBackend,
    PyMuPDFBackend,
)
from intel_agent.extraction.registry import BackendRegistry
from intel_agent.extraction.service import (
    ExtractionProfile,
    ExtractionService,
)
from intel_agent.runtime.config import ExtractionConfig
from intel_agent.runtime.execution import Executor


def _make_pdf(pages: list[str]) -> bytes:
    import pymupdf

    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


async def _import_bytes(resource_store, data: bytes, media_type: str):
    async def chunks():
        for i in range(0, len(data), 64 * 1024):
            yield data[i : i + 64 * 1024]

    return await resource_store.write_stream(
        chunks(),
        origin=ResourceOrigin(acquired_at=datetime.now(UTC)),
        media_type=media_type,
    )


@pytest.fixture
def pdf_service(resource_store):
    registry = BackendRegistry()
    registry.register("pymupdf", PyMuPDFBackend(resource_store))
    registry.register("pdfplumber", PdfplumberBackend(resource_store))
    service = ExtractionService(
        registry, resource_store, Executor(), ExtractionConfig()
    )
    for profile in service.default_profiles():
        service.register_profile(profile)
    return service


async def _extract(pdf_service, data, backend_id):
    resource = await _import_bytes(
        pdf_service.resource_store, data, "application/pdf"
    )
    profile = ExtractionProfile(
        name="pdf", media_type="application/pdf", preferred=backend_id
    )
    pid = pdf_service.register_profile(profile)
    return await pdf_service.extract(resource, pid)


@pytest.mark.parametrize("backend_id", ["pymupdf", "pdfplumber"])
async def test_pdf_backends_extract_per_page(pdf_service, backend_id):
    data = _make_pdf(["Page one content", "Page two content",
                      "Page three content"])
    result = await _extract(pdf_service, data, backend_id)
    assert result.status == "success"
    pages = {block.locator.page for block in result.blocks}
    assert pages == {1, 2, 3}
