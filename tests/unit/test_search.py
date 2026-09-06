"""SearchService dedup, merge, and status tests (T04)."""

from __future__ import annotations

import asyncio
import inspect
from datetime import UTC, datetime

import pytest

from intel_agent.contracts.ports import ProviderCapabilities
from intel_agent.contracts.research import (
    SearchHit,
    SearchOccurrence,
    SearchQuery,
    SearchRequest,
)
from intel_agent.runtime.config import SearchConfig
from intel_agent.search._util import make_hit
from intel_agent.search.dedup import dedup_key
from intel_agent.search.service import SearchService


@pytest.mark.parametrize(
    "left,right",
    [
        ("https://example.org/a", "https://example.org/a/"),
        ("http://example.org/a", "https://example.org/a"),
        ("https://example.org/#/a", "https://example.org/#/b"),
    ],
)
def test_conservative_keys_do_not_merge_distinct_sources(left, right):
    assert dedup_key(left) != dedup_key(right)


def test_dedup_key_normalizes_host_case_and_default_port():
    assert dedup_key("https://Example.ORG/a") == dedup_key(
        "https://example.org/a"
    )
    assert dedup_key("https://example.org:443/a") == dedup_key(
        "https://example.org/a"
    )


def test_dedup_key_strips_tracking_params():
    assert dedup_key(
        "https://x/a?utm_source=s&id=1", ("utm_source",)
    ) == dedup_key("https://x/a?id=1")


def test_make_hit_passes_content_through():
    query = SearchQuery(text="battery recycling")
    hit = make_hit(
        "tavily",
        query,
        "https://example.org/a",
        title="t",
        snippet="s",
        published_at=None,
        source_types=["web"],
        rank=1,
        score=0.9,
        content="clean page text",
    )
    assert hit.content == "clean page text"
    assert hit.occurrences[0].provider_score == 0.9


class FakeProvider:
    def __init__(self, name, hits_fn):
        self.name = name
        self._hits_fn = hits_fn

    def capabilities(self):
        return ProviderCapabilities(source_types=["web"])

    async def search(self, query, limit):
        result = self._hits_fn(query, limit)
        if inspect.isawaitable(result):
            result = await result
        return result


def _hit(url, provider, rank=1, published_at=None):
    return SearchHit(
        hit_id=f"hit-{url}",
        url=url,
        dedup_key=dedup_key(url),
        title="t",
        source_types=["web"],
        published_at=published_at,
        occurrences=[
            SearchOccurrence(
                provider=provider,
                query_id="q1",
                provider_rank=rank,
                observed_at=datetime.now(UTC),
                original_url=url,
                channel="web",
            )
        ],
    )


def test_merge_keeps_occurrences_and_no_score_mixing():
    async def run():
        service = SearchService(
            [
                FakeProvider(
                    "a", lambda q, limit: [_hit("https://x/p", "a", 1)]
                ),
                FakeProvider(
                    "b", lambda q, limit: [_hit("https://x/p", "b", 3)]
                ),
            ],
            SearchConfig(),
        )
        batch = await service.search(
            SearchRequest(
                query=SearchQuery(text="q"),
                per_provider_limit=10,
                total_limit=10,
            )
        )
        assert len(batch.hits) == 1
        assert [o.provider for o in batch.hits[0].occurrences] == ["a", "b"]
        return batch

    asyncio.run(run())


def test_one_timeout_one_success_is_partial():
    async def run():
        async def slow(q, limit):
            await asyncio.sleep(10)

        service = SearchService(
            [
                FakeProvider("a", slow),
                FakeProvider(
                    "b", lambda q, limit: [_hit("https://x/p", "b", 1)]
                ),
            ],
            SearchConfig(
                provider_timeout_seconds=0.05, round_deadline_seconds=1.0
            ),
        )
        batch = await service.search(
            SearchRequest(
                query=SearchQuery(text="q"),
                per_provider_limit=10,
                total_limit=10,
            )
        )
        assert batch.status == "partial"
        assert any(r.status == "timeout" for r in batch.provider_reports)
        return batch

    asyncio.run(run())


def test_all_failed_is_failed():
    async def run():
        def boom(q, limit):
            raise RuntimeError("boom")

        service = SearchService([FakeProvider("a", boom)], SearchConfig())
        batch = await service.search(
            SearchRequest(
                query=SearchQuery(text="q"),
                per_provider_limit=10,
                total_limit=10,
            )
        )
        assert batch.status == "failed"

    asyncio.run(run())


def test_no_providers_returns_empty_batch():
    async def run():
        service = SearchService([], SearchConfig())
        batch = await service.search(
            SearchRequest(
                query=SearchQuery(text="q"),
                per_provider_limit=10,
                total_limit=10,
            )
        )
        assert batch.status == "failed"
        assert batch.hits == []

    asyncio.run(run())


def test_date_postfilter_excludes_unknown_dates():
    async def run():
        published = datetime(2025, 1, 1, tzinfo=UTC)
        service = SearchService(
            [
                FakeProvider(
                    "a",
                    lambda q, limit: [
                        _hit("https://x/known", "a", published_at=published),
                        _hit("https://x/unknown", "a"),
                    ],
                )
            ],
            SearchConfig(),
        )
        batch = await service.search(
            SearchRequest(
                query=SearchQuery(
                    text="q", start_date=datetime(2024, 1, 1).date()
                ),
                per_provider_limit=10,
                total_limit=10,
            )
        )
        assert [h.url for h in batch.hits] == ["https://x/known"]

    asyncio.run(run())
