"""Multimodal import end-to-end: real PDF/image/Office/video (spec A09–A15)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from intel_agent.contracts.documents import NormalizationInput
from intel_agent.contracts.research import ContextRequest

SAMPLES = Path(__file__).resolve().parent.parent.parent / "samples"
MANIFEST = (
    Path(__file__).resolve().parent.parent / "fixtures" / "manifest.json"
)


def load_manifest() -> list[dict]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))["fixtures"]


def _media_type_for(fixture: dict) -> str:
    return fixture["media_type"]


def _fixture_path(fixture: dict) -> Path:
    return SAMPLES / fixture["file"]


async def _import_and_extract(harness, fixture):
    path = _fixture_path(fixture)
    resource = await harness.resource_store.import_file(path)
    media_type = _media_type_for(fixture)
    profile_id = harness.extraction.profile_for(media_type)
    if profile_id is None:
        pytest.skip(f"no profile for {media_type}")
    result = await harness.extraction.extract(resource, profile_id)
    return resource, result


async def _run(harness, fixture):
    task = harness.task_store.create_task(fixture["fixture_id"])
    resource, result = await _import_and_extract(harness, fixture)
    identity = harness.store.resolve_identity(fixture["fixture_id"])
    revision = harness.store.resolve_revision(
        identity.document_id, resource.resource_id
    )
    normalizer = harness.normalizer
    document = normalizer.normalize(
        NormalizationInput(
            result=result,
            resource_id=resource.resource_id,
            identity=identity,
            revision_id=revision,
        )
    )
    artifact_id = harness.store.save_document(task.task_id, document)
    await harness.indexing.index(artifact_id)
    context = await harness.context.build(
        ContextRequest(
            task_id=task.task_id,
            query=fixture["fixture_id"],
            max_tokens=20000,
        )
    )
    return result, document, context


@pytest.mark.real_backend
@pytest.mark.parametrize(
    "fixture_id",
    [
        "pdf-attention",
        "ocr-en",
        "ocr-zh",
        "docx-sample",
        "xlsx-formula",
        "pptx-sample",
        "video-subtitle",
        "video-nosub",
    ],
)
async def test_import_extract_and_retrieve_real_fixture(harness, fixture_id):
    fixture = next(f for f in load_manifest() if f["fixture_id"] == fixture_id)
    if not _fixture_path(fixture).exists():
        pytest.skip(f"sample not downloaded: {fixture['file']}")
    result, document, context = await _run(harness, fixture)
    assert result.status in ("success", "partial")
    assert document.blocks, "no blocks extracted"
    all_text = " ".join(b.text for b in document.blocks).lower()
    evidence = fixture["expected_evidence"]
    matches = sum(1 for item in evidence if item["text"].lower() in all_text)
    assert matches >= 1, f"no evidence found; blocks={all_text[:300]}"


@pytest.mark.real_backend
async def test_uncached_formula_is_not_a_value(harness):
    fixture = next(
        f for f in load_manifest() if f["fixture_id"] == "xlsx-formula"
    )
    if not _fixture_path(fixture).exists():
        pytest.skip("sample not downloaded")
    resource = await harness.resource_store.import_file(_fixture_path(fixture))
    profile_id = harness.extraction.profile_for(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    result = await harness.extraction.extract(resource, profile_id)
    cells = [b for b in result.blocks if b.locator.cell_range == "B2"]
    assert cells
    assert cells[0].metadata.get("formula") == "=A2*2"
    assert cells[0].metadata.get("cached_value") is None
    assert "uncalculated_formula" in result.warnings


@pytest.mark.real_backend
async def test_pdf_preserves_page_locators(harness):
    fixture = next(
        f for f in load_manifest() if f["fixture_id"] == "pdf-attention"
    )
    if not _fixture_path(fixture).exists():
        pytest.skip("sample not downloaded")
    resource, result = await _import_and_extract(harness, fixture)
    pages = {b.locator.page for b in result.blocks if b.locator.page}
    assert pages, "no page locators"
    assert len(pages) >= 2


@pytest.mark.real_backend
async def test_video_subtitle_and_frame_paths(harness):
    for fixture_id in ("video-subtitle", "video-nosub"):
        fixture = next(
            f for f in load_manifest() if f["fixture_id"] == fixture_id
        )
        if not _fixture_path(fixture).exists():
            pytest.skip("sample not downloaded")
        result, document, context = await _run(harness, fixture)
        text = " ".join(b.text for b in document.blocks).lower()
        assert text, f"{fixture_id} produced no text"
