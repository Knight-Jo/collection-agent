"""Persistent crawl frontier, policy, cache, and security tests."""

from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import pytest

import intel_agent.crawl as crawl_module
from intel_agent.config import CrawlConfig
from intel_agent.crawl import crawl_collect, create_crawl, enqueue_url
from intel_agent.evidence import load_document
from intel_agent.fetch import (
    FetchedResponse,
    canonicalize_url,
    parse_http_response,
)
from intel_agent.models import CrawlSnapshot, ExtractionResult, IntelError
from intel_agent.storage import (
    load_crawl,
    read_json_object,
    save_crawl,
    verify_document_integrity,
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


def test_oversized_response_error_reports_downloaded_body_bytes():
    raw = b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\n12345"

    with pytest.raises(IntelError) as error:
        parse_http_response(raw, max_bytes=3)

    assert error.value.code == "RESPONSE_TOO_LARGE"
    assert error.value.downloaded_bytes == 5


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
            return FetchedResponse(status=500, body=b"fail")
        if calls == 2:
            return FetchedResponse(
                status=429,
                headers={"retry-after": "0"},
                body=b"busy",
            )
        return FetchedResponse(
            status=200,
            headers={"content-type": "text/plain", "etag": '"v1"'},
            body=b"12345",
        )

    snapshot = await crawl_collect(
        cwd,
        task.id,
        ["https://example.com/a"],
        config=CrawlConfig(retries=2, max_total_bytes=10, obey_robots=False),
        fetcher=fetcher,
        resolver=_public_resolver,
    )

    entry = snapshot.entries[0]
    assert calls == 3
    assert entry.attempts == 3
    assert entry.status == "skipped_limit"
    assert entry.downloaded_bytes == 13
    assert snapshot.downloaded_bytes == 13
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
async def test_fresh_cache_reuse_preserves_recursive_discovery(cwd):
    first_task = new_task(cwd)

    async def first_fetcher(url, init, address):
        body = (
            b'<html><a href="/next">next</a>root</html>'
            if url.endswith("/root")
            else b"next"
        )
        return FetchedResponse(
            status=200,
            headers={"content-type": "text/html"},
            body=body,
        )

    await crawl_collect(
        cwd,
        first_task.id,
        ["https://example.com/root"],
        config=CrawlConfig(
            max_depth=1, obey_robots=False, per_host_delay_seconds=0
        ),
        fetcher=first_fetcher,
        resolver=_public_resolver,
    )
    second_task = new_task(cwd)

    async def must_not_fetch(url, init, address):
        raise AssertionError("fresh cached crawl must not fetch")

    snapshot = await crawl_collect(
        cwd,
        second_task.id,
        ["https://example.com/root"],
        config=CrawlConfig(
            max_depth=1, obey_robots=False, per_host_delay_seconds=0
        ),
        fetcher=must_not_fetch,
        resolver=_public_resolver,
    )

    assert {entry.canonical_url for entry in snapshot.entries} == {
        "https://example.com/root",
        "https://example.com/next",
    }
    assert {entry.status for entry in snapshot.entries} == {"reused"}


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
    assert snapshot.entries[0].downloaded_bytes == len(response.body)
    assert snapshot.downloaded_bytes == len(response.body)


@pytest.mark.asyncio
async def test_crawl_counts_redirect_response_bodies(cwd):
    task = new_task(cwd)

    async def fetcher(url, init, address):
        if url.endswith("/start"):
            return FetchedResponse(
                status=302,
                headers={"location": "/missing"},
                body=b"hop",
            )
        return FetchedResponse(status=404, body=b"gone")

    snapshot = await crawl_collect(
        cwd,
        task.id,
        ["https://example.com/start"],
        config=CrawlConfig(obey_robots=False, per_host_delay_seconds=0),
        fetcher=fetcher,
        resolver=_public_resolver,
    )

    assert snapshot.entries[0].status == "skipped_http"
    assert snapshot.entries[0].downloaded_bytes == 7
    assert snapshot.downloaded_bytes == 7


@pytest.mark.asyncio
async def test_exact_total_cap_stops_before_next_redirect_hop(cwd):
    task = new_task(cwd)
    fetched: list[str] = []

    async def fetcher(url, init, address):
        fetched.append(url)
        if url.endswith("/start"):
            return FetchedResponse(
                status=302,
                headers={"location": "/must-not-fetch"},
                body=b"full",
            )
        raise AssertionError("redirect hop exceeded the crawl byte cap")

    snapshot = await crawl_collect(
        cwd,
        task.id,
        ["https://example.com/start"],
        config=CrawlConfig(
            max_total_bytes=4,
            obey_robots=False,
            per_host_delay_seconds=0,
        ),
        fetcher=fetcher,
        resolver=_public_resolver,
    )

    assert fetched == ["https://example.com/start"]
    assert snapshot.entries[0].status == "skipped_limit"
    assert snapshot.downloaded_bytes == 4


@pytest.mark.asyncio
async def test_final_response_can_complete_at_exact_total_cap(cwd):
    task = new_task(cwd)

    async def fetcher(url, init, address):
        return FetchedResponse(
            status=200,
            headers={"content-type": "text/plain"},
            body=b"full",
        )

    snapshot = await crawl_collect(
        cwd,
        task.id,
        ["https://example.com/final"],
        config=CrawlConfig(
            max_total_bytes=4,
            obey_robots=False,
            per_host_delay_seconds=0,
        ),
        fetcher=fetcher,
        resolver=_public_resolver,
    )

    assert snapshot.entries[0].status == "complete"
    assert snapshot.downloaded_bytes == 4


@pytest.mark.asyncio
async def test_crawl_counts_body_from_streaming_size_rejection(cwd):
    task = new_task(cwd)

    async def fetcher(url, init, address):
        raise IntelError(
            "RESPONSE_TOO_LARGE",
            "response exceeded limit",
            downloaded_bytes=5,
        )

    snapshot = await crawl_collect(
        cwd,
        task.id,
        ["https://example.com/large"],
        config=CrawlConfig(
            retries=0, obey_robots=False, per_host_delay_seconds=0
        ),
        fetcher=fetcher,
        resolver=_public_resolver,
    )

    assert snapshot.entries[0].status == "skipped_limit"
    assert snapshot.entries[0].downloaded_bytes == 5
    assert snapshot.downloaded_bytes == 5


@pytest.mark.asyncio
async def test_crawl_counts_oversized_returned_resource(cwd):
    task = new_task(cwd)

    async def fetcher(url, init, address):
        return FetchedResponse(
            status=200,
            headers={"content-type": "text/plain"},
            body=b"large",
        )

    snapshot = await crawl_collect(
        cwd,
        task.id,
        ["https://example.com/large"],
        config=CrawlConfig(
            max_attachment_bytes=3,
            obey_robots=False,
            per_host_delay_seconds=0,
        ),
        fetcher=fetcher,
        resolver=_public_resolver,
    )

    assert snapshot.entries[0].status == "skipped_limit"
    assert snapshot.entries[0].downloaded_bytes == 5
    assert snapshot.downloaded_bytes == 5


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
async def test_reprocessing_metadata_failure_preserves_prior_document(
    cwd, monkeypatch
):
    first_task = new_task(cwd)

    async def fetcher(url, init, address):
        return FetchedResponse(
            status=200,
            headers={"content-type": "image/png"},
            body=b"same original",
        )

    monkeypatch.setattr(
        crawl_module,
        "extract_resource",
        lambda *args, **kwargs: ExtractionResult(
            status="unavailable", error="processor missing"
        ),
    )
    first = await crawl_collect(
        cwd,
        first_task.id,
        ["https://example.com/reprocess.png"],
        config=CrawlConfig(obey_robots=False, per_host_delay_seconds=0),
        fetcher=fetcher,
        resolver=_public_resolver,
    )
    document_id = first.entries[0].document_id
    assert document_id
    prior = load_document(cwd, document_id)
    assert prior.extraction_status == "unavailable"
    prior_text = (cwd / prior.text_path).read_bytes()

    monkeypatch.setattr(
        crawl_module,
        "extract_resource",
        lambda *args, **kwargs: ExtractionResult(
            status="complete", text="new extracted text"
        ),
    )
    real_write_json = crawl_module.write_json_atomic

    def fail_document_metadata(cwd_arg, path, value):
        if path == f"documents/{document_id}.json":
            raise OSError("metadata write failed")
        return real_write_json(cwd_arg, path, value)

    monkeypatch.setattr(
        crawl_module, "write_json_atomic", fail_document_metadata
    )
    second_task = new_task(cwd)

    with pytest.raises(OSError, match="metadata write failed"):
        await crawl_collect(
            cwd,
            second_task.id,
            ["https://example.com/reprocess.png"],
            config=CrawlConfig(
                cache_ttl_hours=0,
                obey_robots=False,
                per_host_delay_seconds=0,
            ),
            fetcher=fetcher,
            resolver=_public_resolver,
        )

    recovered = load_document(cwd, document_id)
    verify_document_integrity(cwd, recovered)
    assert recovered.extraction_status == "unavailable"
    assert (cwd / recovered.text_path).read_bytes() == prior_text


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


@pytest.mark.asyncio
async def test_redirect_destination_obeys_host_concurrency_and_delay(cwd):
    task = new_task(cwd)
    target_active = 0
    max_target_active = 0
    delays: list[float] = []

    async def fetcher(url, init, address):
        nonlocal target_active, max_target_active
        if "target.example" not in url:
            path = urlparse(url).path
            return FetchedResponse(
                status=302,
                headers={"location": f"https://target.example{path}"},
            )
        target_active += 1
        max_target_active = max(max_target_active, target_active)
        await asyncio.sleep(0)
        target_active -= 1
        return FetchedResponse(
            status=200,
            headers={"content-type": "text/plain"},
            body=b"target",
        )

    async def fake_sleep(delay: float):
        delays.append(delay)

    await crawl_collect(
        cwd,
        task.id,
        ["https://one.example/a", "https://two.example/b"],
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

    assert max_target_active == 1
    assert any(delay > 0 for delay in delays)


@pytest.mark.asyncio
async def test_retry_reports_later_security_error_not_stale_response(cwd):
    task = new_task(cwd)
    calls = 0

    async def fetcher(url, init, address):
        nonlocal calls
        calls += 1
        if calls == 1:
            return FetchedResponse(status=500, body=b"retry")
        raise IntelError("UNSAFE_URL", "blocked on retry")

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

    assert snapshot.entries[0].status == "failed"
    assert "UNSAFE_URL" in (snapshot.entries[0].error or "")


@pytest.mark.asyncio
async def test_crawl_persists_http_terminal_state_and_emits_events(cwd):
    task = new_task(cwd)
    events = []

    async def fetcher(_url, _init, _address):
        return FetchedResponse(status=404, body=b"missing")

    async def on_event(event):
        events.append(event)

    snapshot = await crawl_collect(
        cwd,
        task.id,
        ["https://example.com/missing"],
        config=CrawlConfig(obey_robots=False, per_host_delay_seconds=0),
        fetcher=fetcher,
        resolver=_public_resolver,
        on_event=on_event,
    )

    saved = load_crawl(cwd, task.id)
    assert snapshot.status == saved.status == "complete"
    assert saved.entries[0].status == "skipped_http"
    assert events[0].type == "crawl.started"
    assert events[-1].type == "crawl.completed"
    resource_event = next(
        event for event in events if event.type == "crawl.resource"
    )
    assert resource_event.data["resource"]["status"] == "skipped_http"


@pytest.mark.asyncio
async def test_crawl_cancellation_during_extraction_persists_resumable_entry(
    cwd, monkeypatch
):
    task = new_task(cwd)
    extraction_started = threading.Event()

    async def fetcher(_url, _init, _address):
        return FetchedResponse(
            status=200,
            headers={"content-type": "text/plain"},
            body=b"extract me",
        )

    def extracting(_raw, _mime_type, _url, *, cancellation_event, **_kwargs):
        extraction_started.set()
        cancellation_event.wait()
        return ExtractionResult(status="complete", text="not archived")

    monkeypatch.setattr(crawl_module, "extract_resource", extracting)
    running = asyncio.create_task(
        crawl_collect(
            cwd,
            task.id,
            ["https://example.com/extract"],
            config=CrawlConfig(obey_robots=False, per_host_delay_seconds=0),
            fetcher=fetcher,
            resolver=_public_resolver,
        )
    )
    await asyncio.wait_for(
        asyncio.to_thread(extraction_started.wait), timeout=1
    )
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running

    saved = load_crawl(cwd, task.id)
    assert saved.status == "paused"
    assert saved.entries[0].status == "queued"
