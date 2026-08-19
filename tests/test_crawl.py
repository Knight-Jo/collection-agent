"""Persistent crawl frontier, policy, cache, and security tests."""

from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import pytest

import intel_agent.crawl as crawl_module
import intel_agent.fetch as fetch_module
from intel_agent.browser import RenderedPage
from intel_agent.config import CrawlConfig
from intel_agent.crawl import (
    _fair_batch,
    crawl_collect,
    create_crawl,
    enqueue_url,
)
from intel_agent.evidence import load_document
from intel_agent.fetch import (
    FetchedResponse,
    _read_response_body,
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


def test_canonicalize_url_percent_encodes_raw_non_ascii_path():
    assert canonicalize_url(
        "https://example.com/uploads/微信图片_2025-scaled.jpg"
    ) == (
        "https://example.com/uploads/"
        "%E5%BE%AE%E4%BF%A1%E5%9B%BE%E7%89%87_2025-scaled.jpg"
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
        "per_domain_cap": None,
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
        "enabled_by_default": False,
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
        relevance=1,
    )
    assert not enqueue_url(
        snapshot,
        "https://example.com/deep",
        parent_url="https://example.com/a",
        depth=2,
        relevance=1,
    )
    assert enqueue_url(
        snapshot,
        "https://example.com/b",
        parent_url="https://example.com/a",
        depth=1,
        relevance=1,
    )
    assert not enqueue_url(
        snapshot,
        "https://example.com/c",
        parent_url="https://example.com/a",
        depth=1,
        relevance=1,
    )


def test_duplicate_queued_url_keeps_higher_relevance_at_frontier_limit(cwd):
    snapshot = create_crawl(
        cwd,
        "task-priority-update",
        ["https://example.com/a"],
        CrawlConfig(max_urls=1),
    )
    original_priority = snapshot.entries[0].priority

    assert not enqueue_url(
        snapshot,
        "https://EXAMPLE.com:443/a/?utm_source=search",
        parent_url=None,
        depth=0,
        relevance=3,
    )

    assert snapshot.entries[0].relevance == 3
    assert snapshot.entries[0].priority < original_priority


def test_full_frontier_admits_better_candidate_by_evicting_worst_queued(cwd):
    snapshot = create_crawl(
        cwd,
        "task-frontier-replace",
        ["https://example.com/low"],
        CrawlConfig(max_urls=1),
    )

    assert enqueue_url(
        snapshot,
        "https://example.com/high",
        parent_url=None,
        depth=0,
        relevance=2,
    )
    assert [entry.canonical_url for entry in snapshot.entries] == [
        "https://example.com/high"
    ]


def test_full_frontier_rejects_equal_priority_candidate(cwd):
    snapshot = create_crawl(
        cwd,
        "task-frontier-equal",
        ["https://example.com/first"],
        CrawlConfig(max_urls=1),
    )

    assert not enqueue_url(
        snapshot,
        "https://example.com/equal",
        parent_url=None,
        depth=0,
    )
    assert [entry.canonical_url for entry in snapshot.entries] == [
        "https://example.com/first"
    ]


def test_full_frontier_never_evicts_terminal_entry(cwd):
    snapshot = create_crawl(
        cwd,
        "task-frontier-terminal",
        ["https://example.com/complete"],
        CrawlConfig(max_urls=1),
    )
    snapshot.entries[0].status = "complete"

    assert not enqueue_url(
        snapshot,
        "https://example.com/high",
        parent_url=None,
        depth=0,
        relevance=10,
    )
    assert [entry.canonical_url for entry in snapshot.entries] == [
        "https://example.com/complete"
    ]


def test_frontier_keeps_low_relevance_candidate_when_capacity_exists(cwd):
    snapshot = create_crawl(
        cwd,
        "task-frontier-capacity",
        ["https://example.com/first"],
        CrawlConfig(max_urls=2),
    )

    assert enqueue_url(
        snapshot,
        "https://example.com/low",
        parent_url=None,
        depth=0,
        relevance=0,
    )
    assert snapshot.entries[1].status == "queued"


def test_image_with_zero_relevance_is_not_enqueued(cwd):
    snapshot = create_crawl(
        cwd,
        "task-image-gate",
        ["https://example.com/page"],
        CrawlConfig(max_urls=10),
    )

    assert not enqueue_url(
        snapshot,
        "https://example.com/logo.png",
        parent_url="https://example.com/page",
        depth=1,
        relevance=0,
    )
    assert [entry.canonical_url for entry in snapshot.entries] == [
        "https://example.com/page"
    ]


def test_relevant_image_is_enqueued(cwd):
    snapshot = create_crawl(
        cwd,
        "task-image-relevant",
        ["https://example.com/page"],
        CrawlConfig(max_urls=10),
    )

    assert enqueue_url(
        snapshot,
        "https://example.com/eh216.png",
        parent_url="https://example.com/page",
        depth=1,
        relevance=2,
    )
    assert snapshot.entries[1].canonical_url == (
        "https://example.com/eh216.png"
    )


def test_image_queue_cap_rejects_extra_images(cwd):
    snapshot = create_crawl(
        cwd,
        "task-image-cap",
        ["https://example.com/page"],
        CrawlConfig(max_urls=30),
    )
    for index in range(3):
        assert enqueue_url(
            snapshot,
            f"https://example.com/img{index}.png",
            parent_url="https://example.com/page",
            depth=1,
            relevance=1,
        )
    assert not enqueue_url(
        snapshot,
        "https://example.com/img4.png",
        parent_url="https://example.com/page",
        depth=1,
        relevance=1,
    )
    images = [
        entry
        for entry in snapshot.entries
        if entry.canonical_url.endswith(".png")
    ]
    assert len(images) == 3


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
        body_limit = init["_max_body_bytes"]
        if calls == 1:
            return FetchedResponse(status=500, body=b"fail")
        if calls == 2:
            return FetchedResponse(
                status=429,
                headers={"retry-after": "0"},
                body=b"busy",
            )
        raise IntelError(
            "RESPONSE_TOO_LARGE",
            "response exceeded limit",
            downloaded_bytes=body_limit,
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
    assert entry.downloaded_bytes == 10
    assert snapshot.downloaded_bytes == 10
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
@pytest.mark.parametrize("failure", [TimeoutError(), OSError("reset")])
async def test_crawl_accounts_partial_failed_reads_across_retry(cwd, failure):
    task = new_task(cwd)
    calls = 0

    class Reader:
        def __init__(self):
            self.reads = iter([b"abc", failure])

        async def read(self, _size):
            item = next(self.reads)
            if isinstance(item, BaseException):
                raise item
            return item

    async def fetcher(url, init, address):
        nonlocal calls
        calls += 1
        if calls == 1:
            await _read_response_body(
                Reader(),
                {},
                init["_max_body_bytes"],
                init["_body_progress"],
            )
            raise AssertionError("partial read should fail")
        assert init["_max_body_bytes"] == 2
        raise IntelError(
            "RESPONSE_TOO_LARGE",
            "response exceeded remaining limit",
            downloaded_bytes=init["_max_body_bytes"],
        )

    snapshot = await crawl_collect(
        cwd,
        task.id,
        ["https://example.com/partial"],
        config=CrawlConfig(
            retries=1,
            max_total_bytes=5,
            obey_robots=False,
            per_host_delay_seconds=0,
        ),
        fetcher=fetcher,
        resolver=_public_resolver,
    )

    assert calls == 2
    assert snapshot.downloaded_bytes == 5
    assert snapshot.entries[0].downloaded_bytes == 5
    assert snapshot.entries[0].status == "skipped_limit"


class _PinnedBodyReader:
    def __init__(
        self,
        body: bytes,
        *,
        started: asyncio.Event | None = None,
        block_after_body: bool = False,
    ):
        self.body = body
        self.started = started
        self.block_after_body = block_after_body
        self.sent = False

    async def readuntil(self, _separator):
        return b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\n"

    async def read(self, _size):
        if not self.sent:
            self.sent = True
            if self.started is not None:
                self.started.set()
            return self.body
        if self.block_after_body:
            await asyncio.Future()
        return b""


class _PinnedWriter:
    def write(self, _value):
        pass

    async def drain(self):
        pass

    def close(self):
        pass

    async def wait_closed(self):
        pass


@pytest.mark.asyncio
async def test_real_deadline_accounts_partial_read_before_retry(
    cwd, monkeypatch
):
    task = new_task(cwd)
    started = asyncio.Event()
    readers = iter(
        [
            _PinnedBodyReader(b"abc", started=started, block_after_body=True),
            _PinnedBodyReader(b"xy"),
        ]
    )
    monkeypatch.setattr(crawl_module, "DEFAULT_TIMEOUT_MS", 10)

    async def open_connection(*_args, **_kwargs):
        return next(readers), _PinnedWriter()

    monkeypatch.setattr(
        fetch_module.asyncio, "open_connection", open_connection
    )

    snapshot = await crawl_collect(
        cwd,
        task.id,
        ["http://example.com/deadline"],
        config=CrawlConfig(
            retries=1,
            max_total_bytes=5,
            obey_robots=False,
            per_host_delay_seconds=0,
        ),
        resolver=_public_resolver,
    )

    assert started.is_set()
    assert snapshot.downloaded_bytes == 5
    assert snapshot.entries[0].downloaded_bytes == 5
    assert snapshot.entries[0].status == "complete"


@pytest.mark.asyncio
async def test_explicit_cancellation_persists_partial_read_and_pauses(cwd):
    task = new_task(cwd)
    started = asyncio.Event()
    reader = _PinnedBodyReader(b"abc", started=started, block_after_body=True)

    async def open_connection(*_args, **_kwargs):
        return reader, _PinnedWriter()

    original_open_connection = fetch_module.asyncio.open_connection
    fetch_module.asyncio.open_connection = open_connection

    try:
        running = asyncio.create_task(
            crawl_collect(
                cwd,
                task.id,
                ["http://example.com/cancel"],
                config=CrawlConfig(
                    retries=0,
                    max_total_bytes=5,
                    obey_robots=False,
                    per_host_delay_seconds=0,
                ),
                resolver=_public_resolver,
            )
        )
        await asyncio.wait_for(started.wait(), timeout=1)
        running.cancel()

        with pytest.raises(asyncio.CancelledError):
            await running
    finally:
        fetch_module.asyncio.open_connection = original_open_connection

    saved = load_crawl(cwd, task.id)
    assert saved.status == "paused"
    assert saved.downloaded_bytes == 3
    assert saved.entries[0].downloaded_bytes == 3
    assert saved.entries[0].status == "queued"


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
async def test_stale_browser_cache_is_fetched_without_conditionals(cwd):
    shell = b'<div id="root"></div><script src="/app.js"></script>'
    first_task = new_task(cwd)

    async def fetcher(_url, init, _address):
        assert not init.get("headers")
        return FetchedResponse(
            status=200,
            headers={"content-type": "text/html", "etag": '"shell-v1"'},
            body=shell,
        )

    async def first_renderer(url, _limit, *_args):
        return RenderedPage(
            final_url=url,
            html="<main>first dynamic report</main>",
            downloaded_bytes=20,
            request_count=1,
        )

    first = await crawl_collect(
        cwd,
        first_task.id,
        ["https://example.com/app"],
        config=CrawlConfig(obey_robots=False, per_host_delay_seconds=0),
        fetcher=fetcher,
        resolver=_public_resolver,
        renderer=first_renderer,
    )
    document_id = first.entries[0].document_id or ""
    record = read_json_object(cwd, f"documents/{document_id}.json")
    record["collected_at"] = (
        datetime.now(UTC) - timedelta(hours=25)
    ).isoformat()
    write_json_atomic(cwd, f"documents/{document_id}.json", record)

    second_task = new_task(cwd)

    async def second_renderer(url, _limit, *_args):
        return RenderedPage(
            final_url=url,
            html="<main>updated dynamic report</main>",
            downloaded_bytes=22,
            request_count=1,
        )

    second = await crawl_collect(
        cwd,
        second_task.id,
        ["https://example.com/app"],
        config=CrawlConfig(obey_robots=False, per_host_delay_seconds=0),
        fetcher=fetcher,
        resolver=_public_resolver,
        renderer=second_renderer,
    )

    assert second.entries[0].document_id != document_id


@pytest.mark.asyncio
async def test_fresh_cache_reuse_preserves_recursive_discovery(cwd):
    first_task = new_task(cwd)

    async def first_fetcher(url, init, address):
        body = (
            b'<html><a href="/next">\xe6\xb5\x8b\xe8\xaf\x95\xe4\xb8\xbb\xe9\xa2\x98</a>root</html>'
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
async def test_crawl_obeys_robots_and_drops_zero_relevance_links(cwd):
    task = new_task(cwd)
    fetched: list[str] = []

    async def fetcher(url, init, address):
        fetched.append(url)
        return FetchedResponse(
            status=200,
            headers={"content-type": "text/html"},
            body=(
                b'<html><a href="/next">\xe6\xb5\x8b\xe8\xaf\x95\xe4\xb8\xbb\xe9\xa2\x98</a>'
                b'<a href="/blocked">\xe6\xb5\x8b\xe8\xaf\x95\xe4\xb8\xbb\xe9\xa2\x98</a>'
                b'<a href="/junk">unrelated</a>root</html>'
                if url.endswith("/root")
                else b"next"
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
    assert "https://example.com/junk" not in entries
    assert fetched == [
        "https://example.com/root",
        "https://example.com/next",
    ]


@pytest.mark.asyncio
async def test_anchor_keyword_relevance_prioritizes_and_drops_zero(cwd):
    task = new_task(cwd)
    fetched: list[str] = []

    async def fetcher(url, init, address):
        fetched.append(url)
        body = (
            b'<html><a href="/low">contact</a>'
            b'<a href="/high">\xe6\xb5\x8b\xe8\xaf\x95\xe4\xb8\xbb\xe9\xa2\x98\xe8\xbf\x9b\xe5\xb1\x95</a></html>'
            if url.endswith("/root")
            else b"child"
        )
        return FetchedResponse(
            status=200,
            headers={"content-type": "text/html"},
            body=body,
        )

    snapshot = await crawl_collect(
        cwd,
        task.id,
        ["https://example.com/root"],
        config=CrawlConfig(
            max_depth=1,
            concurrency=1,
            obey_robots=False,
            per_host_delay_seconds=0,
        ),
        fetcher=fetcher,
        resolver=_public_resolver,
    )

    assert fetched == [
        "https://example.com/root",
        "https://example.com/high",
    ]
    children = {
        entry.canonical_url: entry
        for entry in snapshot.entries
        if entry.depth == 1
    }
    assert children["https://example.com/high"].relevance > 0
    assert "https://example.com/low" not in children


@pytest.mark.asyncio
async def test_outbound_pdf_needs_term_match_to_enqueue(cwd):
    task = new_task(cwd)
    fetched: list[str] = []

    async def fetcher(url, init, address):
        fetched.append(url)
        if url.endswith("/root"):
            return FetchedResponse(
                status=200,
                headers={"content-type": "text/html"},
                body=(
                    b'<html><a href="/report.pdf">\xe6\xb5\x8b\xe8\xaf\x95\xe4\xb8\xbb\xe9\xa2\x98'
                    b"\xe6\x94\xbf\xe7\xad\x96</a>"
                    b'<a href="/other.pdf">unrelated</a></html>'
                ),
            )
        return FetchedResponse(
            status=200,
            headers={"content-type": "application/pdf"},
            body=b"%PDF-1.7\n%%EOF",
        )

    snapshot = await crawl_collect(
        cwd,
        task.id,
        ["https://example.com/root"],
        config=CrawlConfig(
            max_depth=1,
            concurrency=1,
            obey_robots=False,
            per_host_delay_seconds=0,
        ),
        fetcher=fetcher,
        resolver=_public_resolver,
    )

    children = {
        entry.canonical_url: entry
        for entry in snapshot.entries
        if entry.depth == 1
    }
    assert children["https://example.com/report.pdf"].relevance > 0
    assert children["https://example.com/report.pdf"].status == "complete"
    assert "https://example.com/other.pdf" not in children
    assert "https://example.com/other.pdf" not in fetched


def test_enqueue_caps_non_first_party_domain_count(cwd):
    snapshot = create_crawl(cwd, "task-cap", [], CrawlConfig(max_urls=150))
    for index in range(15):
        assert enqueue_url(
            snapshot,
            f"https://example.com/page-{index}",
            parent_url=None,
            depth=0,
            relevance=1,
        )
    assert not enqueue_url(
        snapshot,
        "https://example.com/page-16",
        parent_url=None,
        depth=0,
        relevance=1,
    )
    assert enqueue_url(
        snapshot,
        "https://other.example/page-1",
        parent_url=None,
        depth=0,
        relevance=1,
    )


def test_enqueue_exempts_first_party_domains_from_cap(cwd):
    snapshot = create_crawl(cwd, "task-party", [], CrawlConfig(max_urls=150))
    for index in range(20):
        assert enqueue_url(
            snapshot,
            f"https://www.gov.cn/policy-{index}",
            parent_url=None,
            depth=0,
            relevance=1,
        )
    for index in range(20):
        assert enqueue_url(
            snapshot,
            f"https://ir.ehang.com/press-{index}",
            parent_url=None,
            depth=0,
            relevance=1,
        )


def test_enqueue_caps_social_domains_to_tenth_of_frontier(cwd):
    snapshot = create_crawl(cwd, "task-social", [], CrawlConfig(max_urls=150))
    admitted = 0
    for index in range(30):
        if enqueue_url(
            snapshot,
            f"https://etbbs.com/thread-{index}",
            parent_url=None,
            depth=0,
            relevance=1,
        ):
            admitted += 1
    # Frontier-relative cap: the social allowance grows with the entries
    # actually present (run 013a: a 10%-of-max_urls allowance let a stock
    # bar flood a small corpus to 36%).
    assert admitted == 2


def test_resume_with_duplicate_seeds_keeps_complete_status(cwd):
    task = create_crawl(
        cwd, "task-status", ["https://example.com/a"], CrawlConfig()
    )
    for entry in task.entries:
        entry.status = "complete"
    save_crawl(cwd, task)
    task.status = "complete"
    save_crawl(cwd, task)

    resumed = create_crawl(
        cwd, "task-status", ["https://example.com/a"], CrawlConfig()
    )

    assert resumed.status == "complete"


def test_resume_with_new_seed_reopens_crawl(cwd):
    task = create_crawl(
        cwd, "task-reopen", ["https://example.com/a"], CrawlConfig()
    )
    for entry in task.entries:
        entry.status = "complete"
    task.status = "complete"
    save_crawl(cwd, task)

    resumed = create_crawl(
        cwd, "task-reopen", ["https://example.com/b"], CrawlConfig()
    )

    assert resumed.status == "running"


def test_fair_batch_rotates_across_domains(cwd):
    snapshot = create_crawl(cwd, "task-fair", [], CrawlConfig(max_urls=150))
    for index in range(3):
        assert enqueue_url(
            snapshot,
            f"https://example.com/a-{index}",
            parent_url=None,
            depth=0,
            relevance=3,
        )
    assert enqueue_url(
        snapshot,
        "https://other.example/b-0",
        parent_url=None,
        depth=0,
        relevance=1,
    )
    queued = [entry for entry in snapshot.entries if entry.status == "queued"]

    batch = _fair_batch(queued, 2)

    domains = {entry.canonical_url.split("/")[2] for entry in batch}
    assert domains == {"example.com", "other.example"}


@pytest.mark.asyncio
async def test_crawl_reuses_same_content_republish(cwd):
    task = new_task(cwd)

    async def fetcher(url, init, address):
        return FetchedResponse(
            status=200,
            headers={"content-type": "text/html"},
            body=b"identical republished article body",
        )

    snapshot = await crawl_collect(
        cwd,
        task.id,
        ["https://example.com/original", "https://other.example/repost"],
        config=CrawlConfig(
            max_depth=0,
            concurrency=1,
            obey_robots=False,
            per_host_delay_seconds=0,
        ),
        fetcher=fetcher,
        resolver=_public_resolver,
    )

    statuses = {
        entry.canonical_url: entry.status for entry in snapshot.entries
    }
    assert statuses["https://example.com/original"] == "complete"
    assert statuses["https://other.example/repost"] == "reused"
    documents = list((cwd / "data/intel/documents").glob("*.json"))
    assert len(documents) == 1


@pytest.mark.asyncio
async def test_crawl_persists_complete_status_when_done(cwd):
    task = new_task(cwd)

    async def fetcher(url, init, address):
        return FetchedResponse(
            status=200,
            headers={"content-type": "text/html"},
            body=b"seed content",
        )

    snapshot = await crawl_collect(
        cwd,
        task.id,
        ["https://example.com/seed"],
        config=CrawlConfig(
            max_depth=0,
            obey_robots=False,
            per_host_delay_seconds=0,
        ),
        fetcher=fetcher,
        resolver=_public_resolver,
    )

    assert snapshot.status == "complete"
    from intel_agent.storage import load_crawl

    assert load_crawl(cwd, task.id).status == "complete"


@pytest.mark.asyncio
async def test_crawl_httpx_fallback_after_pinned_network_failure(
    monkeypatch, cwd
):
    task = new_task(cwd)
    calls: list[str] = []

    async def failing_pinned(*_args, **_kwargs):
        calls.append("pinned")
        raise OSError("pinned connection failed")

    async def fake_httpx(url, _init, _address, max_bytes):
        calls.append("httpx")
        return FetchedResponse(
            status=200,
            headers={"content-type": "text/html"},
            body=b"fallback content",
        )

    monkeypatch.setattr(crawl_module, "pinned_fetch", failing_pinned)
    monkeypatch.setattr(crawl_module, "httpx_fallback_fetch", fake_httpx)

    snapshot = await crawl_collect(
        cwd,
        task.id,
        ["https://example.com/root"],
        config=CrawlConfig(
            max_depth=0, obey_robots=False, per_host_delay_seconds=0
        ),
        resolver=_public_resolver,
        httpx_fallback=True,
    )

    assert calls == ["pinned", "httpx"]
    assert snapshot.entries[0].status == "complete"
    assert snapshot.entries[0].document_id


@pytest.mark.asyncio
async def test_crawl_httpx_fallback_normalizes_fallback_errors(
    monkeypatch, cwd
):
    task = new_task(cwd)

    async def failing_pinned(*_args, **_kwargs):
        raise OSError("pinned connection failed")

    async def failing_httpx(*_args, **_kwargs):
        raise RuntimeError("tls verification failed")

    monkeypatch.setattr(crawl_module, "pinned_fetch", failing_pinned)
    monkeypatch.setattr(crawl_module, "httpx_fallback_fetch", failing_httpx)

    snapshot = await crawl_collect(
        cwd,
        task.id,
        ["https://example.com/root"],
        config=CrawlConfig(
            max_depth=0,
            obey_robots=False,
            per_host_delay_seconds=0,
            retries=0,
        ),
        resolver=_public_resolver,
        httpx_fallback=True,
    )

    # Both paths failed: the entry must settle into a terminal status so the
    # queue empties and coverage can proceed (run 020 regression).
    assert snapshot.entries[0].status == "failed"
    assert "pinned 与 httpx 回退均失败" in (snapshot.entries[0].error or "")
    assert snapshot.status == "complete"


@pytest.mark.asyncio
async def test_crawl_httpx_fallback_off_keeps_pinned_error(monkeypatch, cwd):
    task = new_task(cwd)

    async def failing_pinned(*_args, **_kwargs):
        raise OSError("pinned connection failed")

    monkeypatch.setattr(crawl_module, "pinned_fetch", failing_pinned)

    snapshot = await crawl_collect(
        cwd,
        task.id,
        ["https://example.com/root"],
        config=CrawlConfig(
            max_depth=0,
            obey_robots=False,
            per_host_delay_seconds=0,
            retries=0,
        ),
        resolver=_public_resolver,
        httpx_fallback=False,
    )

    assert snapshot.entries[0].status == "failed"
    assert "pinned connection failed" in (snapshot.entries[0].error or "")


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
async def test_redirect_destination_is_checked_against_its_robots_policy(cwd):
    task = new_task(cwd)
    fetched: list[str] = []

    async def fetcher(url, init, address):
        fetched.append(url)
        if url == "https://one.example/robots.txt":
            return FetchedResponse(status=200, body=b"User-agent: *\nAllow: /")
        if url == "https://one.example/start":
            return FetchedResponse(
                status=302,
                headers={"location": "https://two.example/private"},
                body=b"hop",
            )
        if url == "https://two.example/robots.txt":
            return FetchedResponse(
                status=200, body=b"User-agent: *\nDisallow: /private"
            )
        raise AssertionError(f"robots-blocked redirect was fetched: {url}")

    snapshot = await crawl_collect(
        cwd,
        task.id,
        ["https://one.example/start"],
        config=CrawlConfig(per_host_delay_seconds=0),
        fetcher=fetcher,
        resolver=_public_resolver,
    )

    assert fetched == [
        "https://one.example/robots.txt",
        "https://one.example/start",
        "https://two.example/robots.txt",
    ]
    assert snapshot.entries[0].status == "skipped_robots"
    assert snapshot.downloaded_bytes == sum(
        len(body)
        for body in (
            b"User-agent: *\nAllow: /",
            b"hop",
            b"User-agent: *\nDisallow: /private",
        )
    )


@pytest.mark.asyncio
async def test_robots_fetch_uses_retries_rate_limit_and_byte_accounting(cwd):
    task = new_task(cwd)
    robots_calls = 0
    delays: list[float] = []

    async def fetcher(url, init, address):
        nonlocal robots_calls
        if url.endswith("/robots.txt"):
            robots_calls += 1
            if robots_calls == 1:
                return FetchedResponse(status=500, body=b"retry")
            return FetchedResponse(status=200, body=b"User-agent: *\nAllow: /")
        return FetchedResponse(
            status=200,
            headers={"content-type": "text/plain"},
            body=b"resource",
        )

    async def fake_sleep(delay: float):
        delays.append(delay)

    snapshot = await crawl_collect(
        cwd,
        task.id,
        ["https://example.com/resource"],
        config=CrawlConfig(retries=1, per_host_delay_seconds=1),
        fetcher=fetcher,
        resolver=_public_resolver,
        sleep=fake_sleep,
    )

    assert robots_calls == 2
    assert any(delay > 0 for delay in delays)
    assert snapshot.downloaded_bytes == sum(
        len(body)
        for body in (b"retry", b"User-agent: *\nAllow: /", b"resource")
    )
    assert snapshot.entries[0].status == "complete"


@pytest.mark.asyncio
async def test_robots_fetch_is_bounded_by_crawl_timeout(cwd, monkeypatch):
    task = new_task(cwd)
    monkeypatch.setattr(crawl_module, "DEFAULT_TIMEOUT_MS", 10)
    monkeypatch.setattr(
        crawl_module,
        "extract_resource",
        lambda *_args, **_kwargs: ExtractionResult(
            status="complete", text="resource"
        ),
    )

    async def fetcher(url, init, address):
        if url.endswith("/robots.txt"):
            await asyncio.Future()
        return FetchedResponse(
            status=200,
            headers={"content-type": "text/plain"},
            body=b"resource",
        )

    snapshot = await asyncio.wait_for(
        crawl_collect(
            cwd,
            task.id,
            ["https://example.com/resource"],
            config=CrawlConfig(retries=0, per_host_delay_seconds=0),
            fetcher=fetcher,
            resolver=_public_resolver,
        ),
        timeout=0.25,
    )

    assert snapshot.entries[0].status == "complete"


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
async def test_crawl_stops_attachment_download_at_its_hard_cap(cwd):
    task = new_task(cwd)

    async def fetcher(url, init, address):
        assert init["_max_body_bytes"] == 3
        raise IntelError(
            "RESPONSE_TOO_LARGE",
            "response exceeded limit",
            downloaded_bytes=3,
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
    assert snapshot.entries[0].downloaded_bytes == 3
    assert snapshot.downloaded_bytes == 3


@pytest.mark.asyncio
async def test_crawl_stops_html_download_at_its_smaller_hard_cap(cwd):
    task = new_task(cwd)

    async def fetcher(url, init, address):
        assert init["_max_body_bytes"] == 10
        assert init["_max_html_bytes"] == 3
        raise IntelError(
            "RESPONSE_TOO_LARGE",
            "response exceeded limit",
            downloaded_bytes=3,
        )

    snapshot = await crawl_collect(
        cwd,
        task.id,
        ["https://example.com/large.html"],
        config=CrawlConfig(
            max_total_bytes=10,
            max_html_bytes=3,
            max_attachment_bytes=10,
            obey_robots=False,
            per_host_delay_seconds=0,
        ),
        fetcher=fetcher,
        resolver=_public_resolver,
    )

    assert snapshot.entries[0].status == "skipped_limit"
    assert snapshot.entries[0].downloaded_bytes == 3
    assert snapshot.downloaded_bytes == 3


@pytest.mark.asyncio
async def test_concurrent_downloads_reserve_the_remaining_global_allowance(
    cwd,
):
    task = new_task(cwd)
    granted_budgets: list[int] = []

    async def fetcher(url, init, address):
        budget = init["_max_body_bytes"]
        granted_budgets.append(budget)
        await asyncio.sleep(0)
        return FetchedResponse(
            status=200,
            headers={"content-type": "text/plain"},
            body=b"x" * budget,
        )

    snapshot = await crawl_collect(
        cwd,
        task.id,
        ["https://one.example/a.txt", "https://two.example/b.txt"],
        config=CrawlConfig(
            max_total_bytes=10,
            max_attachment_bytes=10,
            concurrency=2,
            obey_robots=False,
            per_host_delay_seconds=0,
        ),
        fetcher=fetcher,
        resolver=_public_resolver,
    )

    assert sum(granted_budgets) == 10
    assert snapshot.downloaded_bytes == 10
    assert {entry.status for entry in snapshot.entries} == {
        "complete",
        "skipped_limit",
    }


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
            status="unavailable", error="tesseract missing"
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

    from intel_agent.evidence import save_evidence
    from intel_agent.fact import save_fact

    fact = save_fact(
        cwd,
        task.id,
        task.questions[0].id,
        "图片显示新增订单",
    )
    with pytest.raises(IntelError) as error:
        save_evidence(cwd, fact.id, document.id, "supports", "新增订单")
    assert error.value.code == "EXTRACTION_UNAVAILABLE"


@pytest.mark.asyncio
async def test_crawl_archives_html_title_and_publish_time(cwd):
    task = new_task(cwd)

    async def fetcher(_url, _init, _address):
        return FetchedResponse(
            status=200,
            headers={"content-type": "text/html"},
            body=(
                b"<title>Quarterly report</title>"
                b'<meta property="article:published_time" content="2026-08-12">'
                b"<p>material update</p>"
            ),
        )

    snapshot = await crawl_collect(
        cwd,
        task.id,
        ["https://example.com/report"],
        config=CrawlConfig(obey_robots=False, per_host_delay_seconds=0),
        fetcher=fetcher,
        resolver=_public_resolver,
    )

    document_id = snapshot.entries[0].document_id
    assert document_id
    document = load_document(cwd, document_id)
    assert document.title == "Quarterly report"
    assert document.publish_time == "2026-08-12"
    assert document.publish_time_source == "meta"


@pytest.mark.asyncio
async def test_crawl_renders_html_shell_and_enqueues_dynamic_links(cwd):
    task = new_task(cwd)
    shell = b'<div id="root"></div><script src="/app.js"></script>'
    child = b"<article>child static report</article>"
    rendered_text = "动态调研正文" * 80
    render_calls = 0

    async def fetcher(url, _init, _address):
        return FetchedResponse(
            status=200,
            headers={"content-type": "text/html"},
            body=child if url.endswith("/next") else shell,
        )

    async def renderer(url: str, _max_bytes: int, *_args) -> RenderedPage:
        nonlocal render_calls
        render_calls += 1
        return RenderedPage(
            final_url=url,
            html=(
                f"<main>{rendered_text}</main>"
                '<a href="https://example.com/next">'
                "\u6d4b\u8bd5\u4e3b\u9898</a>"
            ),
            downloaded_bytes=512,
            request_count=3,
        )

    snapshot = await crawl_collect(
        cwd,
        task.id,
        ["https://example.com/app"],
        config=CrawlConfig(
            max_depth=1, obey_robots=False, per_host_delay_seconds=0
        ),
        fetcher=fetcher,
        resolver=_public_resolver,
        renderer=renderer,
    )

    entry = next(item for item in snapshot.entries if item.depth == 0)
    assert entry.render_reason == "empty_body"
    assert entry.render_error is None
    assert entry.extraction.status == "complete"
    assert entry.extraction.processor == "html-browser"
    assert entry.downloaded_bytes == len(shell) + 512
    assert render_calls == 1
    assert any(
        item.parent_url == entry.canonical_url and item.depth == 1
        for item in snapshot.entries
    )
    document = load_document(cwd, entry.document_id or "")
    assert document.collection_method == "browser"
    assert document.final_url == "https://example.com/app"
    assert document.rendered_url == "https://example.com/app"
    assert rendered_text in (cwd / document.text_path).read_text()


@pytest.mark.asyncio
async def test_crawl_checks_robots_for_browser_navigation_redirects(cwd):
    task = new_task(cwd)
    shell = b'<div id="root"></div><script src="/app.js"></script>'
    checked_urls = []

    async def fetcher(_url, _init, _address):
        return FetchedResponse(
            status=200,
            headers={"content-type": "text/html"},
            body=shell,
        )

    async def robots_allowed(url):
        checked_urls.append(url)
        return "blocked.example" not in url

    async def renderer(
        url, _max_bytes, before_navigation, _on_bytes
    ) -> RenderedPage:
        await before_navigation("https://blocked.example/private")
        return RenderedPage(url, "<main>unreachable</main>", 0, 1)

    snapshot = await crawl_collect(
        cwd,
        task.id,
        ["https://example.com/app"],
        config=CrawlConfig(per_host_delay_seconds=0),
        fetcher=fetcher,
        resolver=_public_resolver,
        robots_allowed=robots_allowed,
        renderer=renderer,
    )

    assert "https://blocked.example/private" in checked_urls
    assert snapshot.entries[0].render_error == (
        "ROBOTS_DISALLOWED: blocked by robots.txt"
    )


@pytest.mark.asyncio
async def test_crawl_charges_browser_bytes_when_render_fails(cwd):
    task = new_task(cwd)
    shell = b'<div id="root"></div><script src="/app.js"></script>'

    async def fetcher(_url, _init, _address):
        return FetchedResponse(
            status=200,
            headers={"content-type": "text/html"},
            body=shell,
        )

    async def renderer(
        _url, _max_bytes, _before_navigation, on_bytes
    ) -> RenderedPage:
        on_bytes(7)
        raise IntelError(
            "RENDER_TIMEOUT", "dynamic response stalled", downloaded_bytes=7
        )

    snapshot = await crawl_collect(
        cwd,
        task.id,
        ["https://example.com/app"],
        config=CrawlConfig(obey_robots=False, per_host_delay_seconds=0),
        fetcher=fetcher,
        resolver=_public_resolver,
        renderer=renderer,
    )

    assert snapshot.entries[0].downloaded_bytes == len(shell) + 7
    assert snapshot.downloaded_bytes == len(shell) + 7


@pytest.mark.asyncio
async def test_crawl_preserves_shell_when_browser_render_fails(cwd):
    task = new_task(cwd)
    shell = b'<div id="root"></div><script src="/app.js"></script>'

    async def fetcher(_url, _init, _address):
        return FetchedResponse(
            status=200,
            headers={"content-type": "text/html"},
            body=shell,
        )

    async def renderer(_url: str, _max_bytes: int, *_args) -> RenderedPage:
        raise IntelError("CHALLENGE_REQUIRED", "页面需要人机验证")

    snapshot = await crawl_collect(
        cwd,
        task.id,
        ["https://example.com/app"],
        config=CrawlConfig(obey_robots=False, per_host_delay_seconds=0),
        fetcher=fetcher,
        resolver=_public_resolver,
        renderer=renderer,
    )

    entry = snapshot.entries[0]
    assert entry.status == "complete"
    assert entry.extraction.status == "unavailable"
    assert entry.render_error == "CHALLENGE_REQUIRED: 页面需要人机验证"
    document = load_document(cwd, entry.document_id or "")
    assert (cwd / document.raw_path).read_bytes() == shell
    assert document.extraction_status == "unavailable"


@pytest.mark.asyncio
async def test_crawl_rejects_browser_bytes_beyond_remaining_budget(cwd):
    task = new_task(cwd)
    shell = b'<div id="root"></div><script src="/app.js"></script>'

    async def fetcher(_url, _init, _address):
        return FetchedResponse(
            status=200,
            headers={"content-type": "text/html"},
            body=shell,
        )

    async def renderer(_url: str, max_bytes: int, *_args) -> RenderedPage:
        return RenderedPage(
            final_url="https://example.com/app",
            html="<main>too large</main>",
            downloaded_bytes=max_bytes + 1,
            request_count=1,
        )

    snapshot = await crawl_collect(
        cwd,
        task.id,
        ["https://example.com/app"],
        config=CrawlConfig(
            max_total_bytes=len(shell) + 10,
            obey_robots=False,
            per_host_delay_seconds=0,
        ),
        fetcher=fetcher,
        resolver=_public_resolver,
        renderer=renderer,
    )

    assert snapshot.entries[0].status == "skipped_limit"
    assert (
        snapshot.entries[0].render_error
        == "RENDER_LIMIT: crawl byte limit reached"
    )


@pytest.mark.asyncio
async def test_crawl_cancellation_during_browser_render_is_resumable(cwd):
    task = new_task(cwd)
    shell = b'<div id="root"></div><script src="/app.js"></script>'
    render_started = asyncio.Event()

    async def fetcher(_url, _init, _address):
        return FetchedResponse(
            status=200,
            headers={"content-type": "text/html"},
            body=shell,
        )

    async def renderer(
        _url: str, _max_bytes: int, _before_navigation, on_bytes
    ) -> RenderedPage:
        on_bytes(4)
        render_started.set()
        await asyncio.Future()
        raise AssertionError("unreachable")

    running = asyncio.create_task(
        crawl_collect(
            cwd,
            task.id,
            ["https://example.com/app"],
            config=CrawlConfig(obey_robots=False, per_host_delay_seconds=0),
            fetcher=fetcher,
            resolver=_public_resolver,
            renderer=renderer,
        )
    )
    await asyncio.wait_for(render_started.wait(), timeout=1)
    running.cancel()

    with pytest.raises(asyncio.CancelledError):
        await running

    saved = load_crawl(cwd, task.id)
    assert saved.status == "paused"
    assert saved.downloaded_bytes == len(shell) + 4
    assert saved.entries[0].downloaded_bytes == len(shell) + 4
    assert saved.entries[0].status == "queued"


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
    real_write_json = fetch_module.write_json_atomic

    def fail_document_metadata(cwd_arg, path, value):
        if path == f"documents/{document_id}.json":
            raise OSError("metadata write failed")
        return real_write_json(cwd_arg, path, value)

    monkeypatch.setattr(
        fetch_module, "write_json_atomic", fail_document_metadata
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
        raise RuntimeError("worker stopped after cancellation")

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


def test_attachment_replaces_lower_value_navigation_when_frontier_is_full(cwd):
    snapshot = create_crawl(
        cwd,
        "task-priority",
        [],
        CrawlConfig(max_urls=1),
    )
    assert enqueue_url(
        snapshot,
        "https://www.gov.cn/index.html",
        parent_url=None,
        depth=1,
        source_priority=1,
        relevance=1,
    )

    assert enqueue_url(
        snapshot,
        "https://example.com/report.pdf",
        parent_url=None,
        depth=1,
        relevance=1,
    )
    assert [entry.canonical_url for entry in snapshot.entries] == [
        "https://example.com/report.pdf"
    ]
