"""Persistent crawl frontier, policy, cache, and security tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from intel_agent.config import CrawlConfig
from intel_agent.crawl import crawl_collect, create_crawl, enqueue_url
from intel_agent.evidence import load_document
from intel_agent.fetch import FetchedResponse, canonicalize_url
from intel_agent.models import CrawlSnapshot, ExtractionResult
from intel_agent.storage import (
    load_crawl,
    read_json_object,
    save_crawl,
    write_json_atomic,
)
from intel_agent.task import load_task
from tests.conftest import new_task


async def _public_resolver(_hostname: str) -> list[str]:
    return ["93.184.216.34"]


def test_canonicalize_url_deduplicates_equivalent_urls():
    assert (
        canonicalize_url(
            "HTTPS://Example.COM:443/a/?utm_source=x&fbclid=f&gclid=g&b=2&a=1#fragment"
        )
        == "https://example.com/a?a=1&b=2"
    )
    assert canonicalize_url("http://EXAMPLE.com:80") == "http://example.com/"
    assert canonicalize_url("https://example.com:8443/a/") == (
        "https://example.com:8443/a"
    )


def test_crawl_config_uses_documented_defaults():
    config = CrawlConfig()
    assert config.model_dump() == {
        "max_depth": 2,
        "max_urls": 200,
        "max_total_bytes": 1_073_741_824,
        "max_html_bytes": 5_242_880,
        "max_attachment_bytes": 52_428_800,
        "concurrency": 4,
        "per_host_concurrency": 1,
        "per_host_delay_seconds": 1.0,
        "cache_ttl_hours": 24,
        "retries": 2,
        "obey_robots": True,
        "ocr_languages": "chi_sim+eng",
        "whisper_model": "small",
        "enabled_by_default": True,
    }


def test_frontier_deduplicates_cycles_depth_and_url_limit(cwd):
    snapshot = create_crawl(
        cwd,
        "task-1",
        ["https://example.com/a#top", "https://EXAMPLE.com:443/a/"],
        CrawlConfig(max_depth=1, max_urls=2),
    )
    assert len(snapshot.entries) == 1
    assert snapshot.entries[0].depth == 0
    assert not enqueue_url(
        snapshot,
        "https://example.com/a?utm_source=loop",
        parent_url="https://example.com/a",
        depth=1,
    )
    assert not enqueue_url(
        snapshot,
        "https://example.com/deep",
        parent_url="https://example.com/a",
        depth=2,
    )
    assert enqueue_url(
        snapshot,
        "https://example.com/b",
        parent_url="https://example.com/a",
        depth=1,
    )
    assert not enqueue_url(
        snapshot,
        "https://example.com/c",
        parent_url="https://example.com/a",
        depth=1,
    )


def test_crawl_snapshot_round_trips_for_resume(cwd):
    snapshot = create_crawl(
        cwd,
        "task-resume",
        ["https://example.com/start"],
        CrawlConfig(),
    )
    snapshot.entries[0].attempts = 1
    snapshot.entries[0].status = "queued"
    save_crawl(cwd, snapshot)

    loaded = load_crawl(cwd, "task-resume")

    assert isinstance(loaded, CrawlSnapshot)
    assert loaded.entries[0].canonical_url == "https://example.com/start"
    assert loaded.entries[0].attempts == 1


@pytest.mark.asyncio
async def test_crawl_retries_and_enforces_byte_limit(cwd):
    task = new_task(cwd)
    calls = 0

    async def fetcher(url, init, address):
        nonlocal calls
        calls += 1
        if calls == 1:
            return FetchedResponse(status=500)
        if calls == 2:
            return FetchedResponse(status=429, headers={"retry-after": "0"})
        return FetchedResponse(
            status=200,
            headers={"content-type": "text/plain", "etag": '"v1"'},
            body=b"12345",
        )

    snapshot = await crawl_collect(
        cwd,
        task.id,
        ["https://example.com/a"],
        config=CrawlConfig(retries=2, max_total_bytes=4, obey_robots=False),
        fetcher=fetcher,
        resolver=_public_resolver,
    )

    entry = snapshot.entries[0]
    assert calls == 3
    assert entry.attempts == 3
    assert entry.status == "skipped_limit"
    assert entry.downloaded_bytes == 0
    assert (
        load_task(cwd, task.id).collection.fetch_attempts_since_evidence == 0
    )


@pytest.mark.asyncio
async def test_crawl_retries_timeout(cwd):
    task = new_task(cwd)
    calls = 0

    async def fetcher(url, init, address):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError
        return FetchedResponse(
            status=200,
            headers={"content-type": "text/plain"},
            body=b"recovered",
        )

    snapshot = await crawl_collect(
        cwd,
        task.id,
        ["https://example.com/retry"],
        config=CrawlConfig(
            retries=1, obey_robots=False, per_host_delay_seconds=0
        ),
        fetcher=fetcher,
        resolver=_public_resolver,
    )

    assert calls == 2
    assert snapshot.entries[0].status == "complete"


@pytest.mark.asyncio
async def test_crawl_reuses_fresh_cross_task_cache_and_revalidates_stale(cwd):
    first_task = new_task(cwd)

    async def first_fetcher(url, init, address):
        return FetchedResponse(
            status=200,
            headers={
                "content-type": "text/plain",
                "etag": '"v1"',
                "last-modified": "Wed, 01 Jan 2025 00:00:00 GMT",
            },
            body=b"cached text",
        )

    first = await crawl_collect(
        cwd,
        first_task.id,
        ["https://example.com/cache"],
        config=CrawlConfig(obey_robots=False, per_host_delay_seconds=0),
        fetcher=first_fetcher,
        resolver=_public_resolver,
    )
    document_id = first.entries[0].document_id

    second_task = new_task(cwd)

    async def must_not_fetch(url, init, address):
        raise AssertionError("fresh cache must not perform a network request")

    second = await crawl_collect(
        cwd,
        second_task.id,
        ["https://example.com/cache#again"],
        config=CrawlConfig(obey_robots=False, per_host_delay_seconds=0),
        fetcher=must_not_fetch,
        resolver=_public_resolver,
    )
    assert second.entries[0].status == "reused"
    assert second.entries[0].document_id == document_id

    old = datetime.now(UTC) - timedelta(hours=25)
    document_record = read_json_object(cwd, f"documents/{document_id}.json")
    document_record["collected_at"] = old.isoformat()
    write_json_atomic(cwd, f"documents/{document_id}.json", document_record)

    request_headers = {}

    async def conditional_fetcher(url, init, address):
        request_headers.update(init["headers"])
        return FetchedResponse(status=304)

    third_task = new_task(cwd)
    third = await crawl_collect(
        cwd,
        third_task.id,
        ["https://example.com/cache"],
        config=CrawlConfig(obey_robots=False, per_host_delay_seconds=0),
        fetcher=conditional_fetcher,
        resolver=_public_resolver,
    )
    assert request_headers == {
        "If-None-Match": '"v1"',
        "If-Modified-Since": "Wed, 01 Jan 2025 00:00:00 GMT",
    }
    assert third.entries[0].status == "reused"
    assert third.entries[0].document_id == document_id


@pytest.mark.asyncio
async def test_crawl_obeys_robots_and_keeps_low_relevance_links_queued(cwd):
    task = new_task(cwd)
    fetched: list[str] = []

    async def fetcher(url, init, address):
        fetched.append(url)
        return FetchedResponse(
            status=200,
            headers={"content-type": "text/html"},
            body=(
                b'<html><a href="/next">unrelated</a>'
                b'<a href="/blocked">blocked</a>root</html>'
            ),
        )

    async def robots_allowed(url: str) -> bool:
        return not url.endswith("/blocked")

    snapshot = await crawl_collect(
        cwd,
        task.id,
        ["https://example.com/root"],
        config=CrawlConfig(max_depth=1, per_host_delay_seconds=0),
        fetcher=fetcher,
        resolver=_public_resolver,
        robots_allowed=robots_allowed,
    )

    entries = {entry.canonical_url: entry for entry in snapshot.entries}
    assert entries["https://example.com/blocked"].status == "skipped_robots"
    assert entries["https://example.com/next"].depth == 1
    assert entries["https://example.com/next"].status == "complete"
    assert fetched == [
        "https://example.com/root",
        "https://example.com/next",
    ]


@pytest.mark.asyncio
async def test_default_robots_policy_uses_crawler_user_agent(cwd):
    task = new_task(cwd)
    fetched: list[str] = []

    async def fetcher(url, init, address):
        fetched.append(url)
        if url.endswith("/robots.txt"):
            return FetchedResponse(
                status=200,
                body=(
                    b"User-agent: pi-intelligence-collector\n"
                    b"Disallow: /private\n"
                ),
            )
        return FetchedResponse(
            status=200,
            headers={"content-type": "text/plain"},
            body=b"private",
        )

    snapshot = await crawl_collect(
        cwd,
        task.id,
        ["https://example.com/private"],
        config=CrawlConfig(per_host_delay_seconds=0),
        fetcher=fetcher,
        resolver=_public_resolver,
    )

    assert fetched == ["https://example.com/robots.txt"]
    assert snapshot.entries[0].status == "skipped_robots"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "expected_status"),
    [
        (FetchedResponse(status=404), "skipped_http"),
        (
            FetchedResponse(
                status=200,
                headers={"content-type": "application/zip"},
                body=b"archive",
            ),
            "skipped_unsupported",
        ),
    ],
)
async def test_crawl_records_http_and_unsupported_skips(
    cwd, response, expected_status
):
    task = new_task(cwd)

    async def fetcher(url, init, address):
        return response

    snapshot = await crawl_collect(
        cwd,
        task.id,
        ["https://example.com/resource"],
        config=CrawlConfig(obey_robots=False, per_host_delay_seconds=0),
        fetcher=fetcher,
        resolver=_public_resolver,
    )

    assert snapshot.entries[0].status == expected_status


@pytest.mark.asyncio
async def test_crawl_preserves_original_when_processor_is_unavailable(
    cwd, monkeypatch
):
    task = new_task(cwd)

    async def fetcher(url, init, address):
        return FetchedResponse(
            status=200,
            headers={"content-type": "image/png"},
            body=b"original image bytes",
        )

    monkeypatch.setattr(
        "intel_agent.crawl.extract_resource",
        lambda *args, **kwargs: ExtractionResult(
            status="unavailable", error="pytesseract missing"
        ),
    )
    snapshot = await crawl_collect(
        cwd,
        task.id,
        ["https://example.com/image.png"],
        config=CrawlConfig(obey_robots=False, per_host_delay_seconds=0),
        fetcher=fetcher,
        resolver=_public_resolver,
    )

    entry = snapshot.entries[0]
    assert entry.status == "complete"
    assert entry.extraction.status == "unavailable"
    assert entry.document_id
    document = load_document(cwd, entry.document_id)
    assert (cwd / document.raw_path).read_bytes() == b"original image bytes"


@pytest.mark.asyncio
async def test_crawl_blocks_ssrf_redirect(cwd):
    task = new_task(cwd)

    async def fetcher(url, init, address):
        return FetchedResponse(
            status=302, headers={"location": "http://127.0.0.1/secret"}
        )

    snapshot = await crawl_collect(
        cwd,
        task.id,
        ["https://example.com/start"],
        config=CrawlConfig(obey_robots=False, per_host_delay_seconds=0),
        fetcher=fetcher,
        resolver=_public_resolver,
    )

    assert snapshot.entries[0].status == "failed"
    assert "UNSAFE_URL" in (snapshot.entries[0].error or "")


@pytest.mark.asyncio
async def test_crawl_hard_deduplicates_redirect_aliases(cwd):
    task = new_task(cwd)

    async def fetcher(url, init, address):
        if url.endswith(("/a", "/b")):
            return FetchedResponse(
                status=302, headers={"location": "/canonical"}
            )
        return FetchedResponse(
            status=200,
            headers={"content-type": "text/plain"},
            body=b"one resource",
        )

    snapshot = await crawl_collect(
        cwd,
        task.id,
        ["https://example.com/a", "https://example.com/b"],
        config=CrawlConfig(obey_robots=False, per_host_delay_seconds=0),
        fetcher=fetcher,
        resolver=_public_resolver,
    )

    assert [entry.canonical_url for entry in snapshot.entries] == [
        "https://example.com/canonical"
    ]


@pytest.mark.asyncio
async def test_crawl_applies_per_host_concurrency_and_delay(cwd):
    task = new_task(cwd)
    active = 0
    max_active = 0
    delays: list[float] = []

    async def fetcher(url, init, address):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0)
        active -= 1
        return FetchedResponse(
            status=200,
            headers={"content-type": "text/plain"},
            body=url.encode(),
        )

    async def fake_sleep(delay: float):
        delays.append(delay)

    await crawl_collect(
        cwd,
        task.id,
        ["https://example.com/a", "https://example.com/b"],
        config=CrawlConfig(
            concurrency=2,
            per_host_concurrency=1,
            per_host_delay_seconds=1,
            obey_robots=False,
        ),
        fetcher=fetcher,
        resolver=_public_resolver,
        sleep=fake_sleep,
    )

    assert max_active == 1
    assert any(delay > 0 for delay in delays)
