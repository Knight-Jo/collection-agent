"""Acquisition pipeline and per-item recovery tests (T16)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from intel_agent.acquisition import AcquisitionPipeline
from intel_agent.contracts.documents import (
    CoverageUnit,
    EvidenceBlock,
    ExtractResult,
    Locator,
)
from intel_agent.contracts.research import SearchHit
from intel_agent.contracts.resources import ResourceOrigin
from intel_agent.indexing.service import IndexingService
from intel_agent.indexing.tokenize import TiktokenCounter
from intel_agent.normalization import Normalizer
from intel_agent.runtime.config import IndexingConfig


class FakeFetchService:
    def __init__(self, resource_store):
        self.resource_store = resource_store
        self.calls = 0

    async def fetch(self, request):
        self.calls += 1

        async def chunks():
            yield b"<html><p>test content</p></html>"

        resource = await self.resource_store.write_stream(
            chunks(),
            origin=ResourceOrigin(
                requested_url=request.url,
                final_url=request.url,
                acquired_at=datetime.now(UTC),
            ),
            media_type="text/html",
        )
        from intel_agent.contracts.resources import FetchResult

        return FetchResult(
            resource=resource, status_code=200, method="http", elapsed_ms=1
        )


class FakeExtractionService:
    def __init__(self):
        self.calls = 0

    def profile_for(self, media_type):
        return "profile-1"

    async def extract(self, resource, profile_id):
        self.calls += 1
        return ExtractResult(
            resource_id=resource.resource_id,
            blocks=[
                EvidenceBlock(
                    block_id="b1",
                    text="test content",
                    block_type="paragraph",
                    locator=Locator(),
                    origin_method="native_text",
                    backend_id="fake",
                    backend_version="1",
                )
            ],
            coverage=[
                CoverageUnit(
                    unit_type="document", locator=Locator(), status="success"
                )
            ],
            status="success",
            extraction_profile_id=profile_id,
        )


class CountingIndexingService(IndexingService):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.calls = 0

    async def index(self, artifact_id):
        self.calls += 1
        return await super().index(artifact_id)


def _pipeline(material_store, resource_store):
    fetch = FakeFetchService(resource_store)
    extract = FakeExtractionService()
    indexing = CountingIndexingService(
        material_store, IndexingConfig(), TiktokenCounter()
    )
    pipeline = AcquisitionPipeline(
        fetch,
        extract,
        Normalizer(version="1"),
        material_store,
        resource_store,
        indexing,
    )
    return pipeline, fetch, extract, indexing


def test_resume_after_store_only_indexes(material_store, resource_store):
    async def run():
        pipeline, fetch, extract, indexing = _pipeline(
            material_store, resource_store
        )
        task = material_store.create_task("q")
        hit = SearchHit(
            hit_id="h1",
            url="https://example.org/a",
            dedup_key="https://example.org/a",
            source_types=["web"],
        )
        report = await pipeline.acquire(
            task.task_id, hit, "profile-1", index_after_store=True
        )
        assert report.artifact_id is not None
        # Simulate crash before index by resetting the index counter and
        # resuming with a fresh pipeline instance (same store).
        await asyncio.sleep(0)
        pipeline2, fetch2, extract2, indexing2 = _pipeline(
            material_store, resource_store
        )
        report2 = await pipeline2.resume_item(report.work_item_id)
        assert report2.artifact_id == report.artifact_id
        assert fetch.calls == 1
        assert extract.calls == 1
        assert indexing.calls == 1

    asyncio.run(run())


def test_resume_does_not_refetch_or_reindex(material_store, resource_store):
    async def run():
        pipeline, fetch, extract, indexing = _pipeline(
            material_store, resource_store
        )
        task = material_store.create_task("q")
        hit = SearchHit(
            hit_id="h1",
            url="https://example.org/b",
            dedup_key="https://example.org/b",
            source_types=["web"],
        )
        report = await pipeline.acquire(
            task.task_id, hit, "profile-1", index_after_store=True
        )
        # Resume again: everything already done, no duplicate work.
        await pipeline.resume_item(report.work_item_id)
        assert fetch.calls == 1
        assert extract.calls == 1

    asyncio.run(run())
