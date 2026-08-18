"""Persistent, task-owned crawl frontier using the DNS-pinned fetch path."""

from __future__ import annotations

import asyncio
import mimetypes
import threading
from collections import Counter
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from .browser import BrowserRender, should_render_html
from .config import CrawlConfig
from .document_extract import decode_body
from .extract import extract_resource_process as extract_resource
from .extract import (
    is_rejected_resource,
    is_supported_resource,
)
from .fetch import (
    DEFAULT_TIMEOUT_MS,
    USER_AGENT,
    BodyProgress,
    FetchedResponse,
    FetchLike,
    archive_document,
    canonicalize_url,
    fetch_with_validated_redirects,
    pinned_fetch,
)
from .models import (
    CrawlEntry,
    CrawlSnapshot,
    CrawlValidators,
    ExtractionState,
    IntelDocument,
    IntelError,
    utc_now,
)
from .search import relevance_tokens
from .security import AddressResolver
from .storage import (
    list_crawls,
    load_crawl,
    read_json,
    save_crawl,
    verify_document_integrity,
)
from .task import load_task

RobotsAllowed = Callable[[str], Awaitable[bool]]
RobotsFetch = Callable[[CrawlEntry, str], Awaitable[FetchedResponse]]
Sleep = Callable[[float], Awaitable[None]]
CrawlEventType = Literal[
    "crawl.started",
    "crawl.progress",
    "crawl.resource",
    "crawl.completed",
]


@dataclass(frozen=True)
class CrawlEvent:
    type: CrawlEventType
    data: dict[str, object]


CrawlEventCallback = Callable[[CrawlEvent], Awaitable[None]]
_ATTACHMENT_SUFFIXES = {
    ".csv",
    ".doc",
    ".docx",
    ".flac",
    ".jpeg",
    ".jpg",
    ".m4a",
    ".mov",
    ".mp3",
    ".mp4",
    ".ogg",
    ".pdf",
    ".png",
    ".ppt",
    ".pptx",
    ".tif",
    ".tiff",
    ".txt",
    ".wav",
    ".webm",
    ".webp",
    ".xls",
    ".xlsx",
}

_IMAGE_SUFFIXES = {".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}


def _image_entry_count(snapshot: CrawlSnapshot) -> int:
    return sum(
        1
        for entry in snapshot.entries
        if Path(urlparse(entry.canonical_url).path).suffix.lower()
        in _IMAGE_SUFFIXES
    )


def _crawl_counts(snapshot: CrawlSnapshot) -> dict[str, int]:
    counts = Counter(entry.status for entry in snapshot.entries)
    return {
        "total": len(snapshot.entries),
        "queued": counts["queued"],
        "fetching": counts["fetching"],
        "complete": counts["complete"],
        "reused": counts["reused"],
        "failed": counts["failed"],
        "skipped": sum(
            count
            for status, count in counts.items()
            if status.startswith("skipped_")
        ),
    }


def _crawl_event_data(snapshot: CrawlSnapshot) -> dict[str, object]:
    return {
        "task_id": snapshot.task_id,
        "status": snapshot.status,
        "downloaded_bytes": snapshot.downloaded_bytes,
        "counts": _crawl_counts(snapshot),
    }


def summarize_crawl(snapshot: CrawlSnapshot) -> dict[str, object]:
    """Return the model-facing crawl summary without the persisted frontier."""
    resources = [
        {
            "url": entry.canonical_url,
            "depth": entry.depth,
            "status": entry.status,
            "document_id": entry.document_id,
            "mime_type": entry.mime_type,
            "size": entry.size,
            "extraction_status": entry.extraction.status,
            **(
                {"error": entry.error or entry.extraction.error}
                if entry.error or entry.extraction.error
                else {}
            ),
        }
        for entry in snapshot.entries
        if entry.status != "queued"
    ]
    return {
        **_crawl_event_data(snapshot),
        "resources": resources[:50],
        "resources_truncated": len(resources) > 50,
    }


def _priority(
    depth: int,
    relevance: float,
    source_priority: float,
    attachment: bool,
) -> float:
    return (
        depth * 100 - relevance * 20 - source_priority * 10 - attachment * 20
    )


def enqueue_url(
    snapshot: CrawlSnapshot,
    raw_url: str,
    *,
    parent_url: str | None,
    depth: int,
    relevance: float = 0,
    source_priority: float = 0,
    attachment: bool | None = None,
) -> bool:
    """Add one canonical URL if it fits this task's hard frontier limits."""
    config = CrawlConfig.model_validate(snapshot.config)
    if depth > config.max_depth:
        return False
    canonical = canonicalize_url(raw_url)
    existing = next(
        (
            entry
            for entry in snapshot.entries
            if entry.canonical_url == canonical
        ),
        None,
    )
    if existing is not None:
        if existing.status == "queued" and relevance > existing.relevance:
            if attachment is None:
                attachment = Path(urlparse(canonical).path).suffix.lower() in (
                    _ATTACHMENT_SUFFIXES
                )
            now = utc_now()
            existing.relevance = relevance
            existing.priority = min(
                existing.priority,
                _priority(
                    existing.depth,
                    relevance,
                    source_priority,
                    bool(attachment),
                ),
            )
            existing.updated_at = now
            snapshot.updated_at = now
        return False
    if attachment is None:
        attachment = Path(urlparse(canonical).path).suffix.lower() in (
            _ATTACHMENT_SUFFIXES
        )
    # Depth≥1 links must earn their slot: zero-relevance outbound links are
    # portal navigation junk (run 009: 48/48 rel-0 docs were junk), while
    # term-matched discoveries pass (run 008: the only useful outbound PDF
    # carried rel 2.0). Seeds (depth 0) are exempt.
    if depth >= 1 and relevance <= 0:
        return False
    if Path(urlparse(canonical).path).suffix.lower() in _IMAGE_SUFFIXES:
        image_cap = max(3, config.max_urls // 10)
        if depth >= 1 and _image_entry_count(snapshot) >= image_cap:
            return False
    candidate_priority = _priority(
        depth, relevance, source_priority, bool(attachment)
    )
    if len(snapshot.entries) >= config.max_urls:
        queued = [
            entry for entry in snapshot.entries if entry.status == "queued"
        ]
        worst = max(queued, key=lambda entry: entry.priority, default=None)
        if worst is None or candidate_priority >= worst.priority:
            return False
        snapshot.entries.remove(worst)
    now = utc_now()
    snapshot.entries.append(
        CrawlEntry(
            canonical_url=canonical,
            parent_url=(canonicalize_url(parent_url) if parent_url else None),
            depth=depth,
            relevance=relevance,
            priority=candidate_priority,
            created_at=now,
            updated_at=now,
        )
    )
    snapshot.updated_at = now
    return True


def create_crawl(
    cwd: Path,
    task_id: str,
    seeds: list[str],
    config: CrawlConfig,
    *,
    seed_relevance: dict[str, float] | None = None,
) -> CrawlSnapshot:
    """Create or resume one task's persisted crawl frontier."""
    try:
        snapshot = load_crawl(cwd, task_id)
        snapshot.config = config.model_dump()
        snapshot.status = "running"
        for entry in snapshot.entries:
            if entry.status == "fetching":
                entry.status = "queued"
    except IntelError as error:
        if error.code != "NOT_FOUND":
            raise
        now = utc_now()
        snapshot = CrawlSnapshot(
            task_id=task_id,
            config=config.model_dump(),
            created_at=now,
            updated_at=now,
        )
    for seed in seeds:
        enqueue_url(
            snapshot,
            seed,
            parent_url=None,
            depth=0,
            relevance=(seed_relevance or {}).get(seed, 0),
        )
    save_crawl(cwd, snapshot)
    return snapshot


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _cached_entry(
    cwd: Path, task_id: str, canonical_url: str
) -> CrawlEntry | None:
    matches = [
        entry
        for snapshot in list_crawls(cwd)
        if snapshot.task_id != task_id
        for entry in snapshot.entries
        if entry.canonical_url == canonical_url
        and entry.status in {"complete", "reused"}
        and entry.document_id
    ]
    return max(
        matches,
        key=lambda item: _parse_time(
            IntelDocument.model_validate(
                read_json(cwd, f"documents/{item.document_id}.json")
            ).collected_at
        ),
        default=None,
    )


def _load_cached_document(cwd: Path, entry: CrawlEntry) -> IntelDocument:
    document = IntelDocument.model_validate(
        read_json(cwd, f"documents/{entry.document_id}.json")
    )
    verify_document_integrity(cwd, document)
    return document


def _copy_cache(entry: CrawlEntry, cached: CrawlEntry) -> None:
    entry.status = "reused"
    entry.document_id = cached.document_id
    entry.mime_type = cached.mime_type
    entry.size = cached.size
    entry.validators = cached.validators.model_copy(deep=True)
    entry.extraction = cached.extraction.model_copy(deep=True)
    entry.outbound_links = list(cached.outbound_links)
    entry.outbound_relevance = dict(cached.outbound_relevance)
    entry.updated_at = utc_now()


def _deduplicate_entries(snapshot: CrawlSnapshot) -> None:
    """Collapse aliases that resolve to the same final canonical URL."""
    unique: dict[str, CrawlEntry] = {}
    for entry in snapshot.entries:
        current = unique.get(entry.canonical_url)
        if current is None or (
            current.status not in {"complete", "reused"}
            and entry.status in {"complete", "reused"}
        ):
            unique[entry.canonical_url] = entry
    snapshot.entries = list(unique.values())


class _RobotsPolicy:
    def __init__(self, fetch: RobotsFetch):
        self.fetch = fetch
        self.parsers: dict[str, RobotFileParser | None] = {}
        self.locks: dict[str, asyncio.Lock] = {}

    async def allowed(
        self,
        entry: CrawlEntry,
        url: str,
        fetch: RobotsFetch | None = None,
    ) -> bool:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        async with self.locks.setdefault(origin, asyncio.Lock()):
            if origin not in self.parsers:
                self.parsers[origin] = await self._load(
                    entry, origin, fetch or self.fetch
                )
        parser = self.parsers[origin]
        return True if parser is None else parser.can_fetch(USER_AGENT, url)

    async def _load(
        self, entry: CrawlEntry, origin: str, fetch: RobotsFetch
    ) -> RobotFileParser | None:
        robots_url = f"{origin}/robots.txt"
        try:
            response = await fetch(entry, robots_url)
        except (IntelError, OSError, TimeoutError):
            return None
        parser = RobotFileParser(robots_url)
        if response.status == 200:
            parser.parse(
                response.body.decode("utf-8", errors="replace").splitlines()
            )
        elif response.status in {401, 403}:
            parser.parse(["User-agent: *", "Disallow: /"])
        else:
            return None
        return parser


class _CrawlRunner:
    def __init__(
        self,
        cwd: Path,
        snapshot: CrawlSnapshot,
        config: CrawlConfig,
        fetcher: FetchLike,
        resolver: AddressResolver | None,
        robots_allowed: RobotsAllowed | None,
        sleep: Sleep,
        on_event: CrawlEventCallback | None,
        relevance_terms: list[str],
        renderer: BrowserRender | None,
    ):
        self.cwd = cwd
        self.snapshot = snapshot
        self.config = config
        self.fetcher = fetcher
        self.resolver = resolver
        self.robots_allowed = robots_allowed
        self.robots_policy = (
            None
            if robots_allowed is not None
            else _RobotsPolicy(self._fetch_robots)
        )
        self.sleep = sleep
        self.on_event = on_event
        self.relevance_terms = relevance_terms
        self.renderer = renderer
        self.global_semaphore = asyncio.Semaphore(config.concurrency)
        self.io_semaphore = asyncio.Semaphore(config.concurrency)
        self.host_semaphores: dict[str, asyncio.Semaphore] = {}
        self.host_locks: dict[str, asyncio.Lock] = {}
        self.host_last_start: dict[str, float] = {}
        self.persist_lock = asyncio.Lock()
        # ponytail: global byte lock serializes downloads; reserve ranges if
        # throughput matters.
        self.byte_lock = asyncio.Lock()
        self.resource_statuses = {
            id(entry): entry.status for entry in snapshot.entries
        }

    async def persist(self) -> None:
        async with self.persist_lock:
            self.snapshot.updated_at = utc_now()
            save_crawl(self.cwd, self.snapshot)
            if self.on_event is None:
                return
            terminal = {
                "complete",
                "reused",
                "skipped_robots",
                "skipped_http",
                "skipped_limit",
                "skipped_unsupported",
                "failed",
            }
            for entry in self.snapshot.entries:
                previous = self.resource_statuses.get(id(entry))
                self.resource_statuses[id(entry)] = entry.status
                if entry.status in terminal and entry.status != previous:
                    await self.on_event(
                        CrawlEvent(
                            "crawl.resource",
                            {
                                **_crawl_event_data(self.snapshot),
                                "resource": entry.model_dump(),
                            },
                        )
                    )
            await self.on_event(
                CrawlEvent("crawl.progress", _crawl_event_data(self.snapshot))
            )

    async def rate_limit(self, hostname: str) -> None:
        loop = asyncio.get_running_loop()
        async with self.host_locks.setdefault(hostname, asyncio.Lock()):
            elapsed = loop.time() - self.host_last_start.get(hostname, 0)
            delay = self.config.per_host_delay_seconds - elapsed
            if delay > 0:
                await self.sleep(delay)
            self.host_last_start[hostname] = loop.time()

    async def _fetch_hop(
        self,
        entry: CrawlEntry,
        url: str,
        request_init: dict | None,
        address: str,
        *,
        body_limit: int | None = None,
    ) -> FetchedResponse:
        hostname = urlparse(url).hostname or ""
        host_semaphore = self.host_semaphores.setdefault(
            hostname, asyncio.Semaphore(self.config.per_host_concurrency)
        )
        async with self.io_semaphore, host_semaphore:
            await self.rate_limit(hostname)
            async with self.byte_lock:
                return await self._fetch_hop_with_budget(
                    entry, url, request_init, address, body_limit
                )

    async def _fetch_hop_with_budget(
        self,
        entry: CrawlEntry,
        url: str,
        request_init: dict | None,
        address: str,
        body_limit: int | None,
    ) -> FetchedResponse:
        """Fetch while the caller owns the crawl byte-budget lock."""
        remaining = (
            self.config.max_total_bytes - self.snapshot.downloaded_bytes
        )
        if remaining <= 0:
            raise IntelError("CRAWL_LIMIT", "crawl byte limit reached")
        attachment_limit = min(
            remaining,
            body_limit or self.config.max_attachment_bytes,
        )
        html_limit = min(attachment_limit, self.config.max_html_bytes)
        bounded_init = {
            **(request_init or {}),
            "_max_body_bytes": attachment_limit,
            "_max_html_bytes": html_limit,
        }
        body_progress = BodyProgress()
        bounded_init["_body_progress"] = body_progress
        try:
            response = await self.fetcher(url, bounded_init, address)
        except asyncio.CancelledError:
            downloaded = min(body_progress.downloaded_bytes, attachment_limit)
            if downloaded:
                entry.downloaded_bytes += downloaded
                self.snapshot.downloaded_bytes += downloaded
                await asyncio.shield(self.persist())
            raise
        except IntelError as error:
            downloaded = min(
                max(
                    body_progress.downloaded_bytes,
                    error.downloaded_bytes,
                    0,
                ),
                attachment_limit,
            )
            if downloaded:
                entry.downloaded_bytes += downloaded
                self.snapshot.downloaded_bytes += downloaded
                await self.persist()
            raise
        mime_type = response.headers.get("content-type", "").split(";", 1)[0]
        response_limit = (
            html_limit
            if mime_type in {"text/html", "application/xhtml+xml"}
            else attachment_limit
        )
        downloaded = min(len(response.body), response_limit)
        if downloaded:
            entry.downloaded_bytes += downloaded
            self.snapshot.downloaded_bytes += downloaded
            await self.persist()
        if len(response.body) > response_limit:
            raise IntelError(
                "RESPONSE_TOO_LARGE",
                f"response exceeded {response_limit} bytes",
            )
        return response

    async def _fetch_hop_during_render(
        self,
        entry: CrawlEntry,
        url: str,
        request_init: dict | None,
        address: str,
        *,
        body_limit: int | None = None,
        held_hostname: str,
    ) -> FetchedResponse:
        hostname = urlparse(url).hostname or ""

        async def fetch() -> FetchedResponse:
            await self.rate_limit(hostname)
            return await self._fetch_hop_with_budget(
                entry, url, request_init, address, body_limit
            )

        if hostname == held_hostname:
            return await fetch()
        host_semaphore = self.host_semaphores.setdefault(
            hostname, asyncio.Semaphore(self.config.per_host_concurrency)
        )
        async with self.io_semaphore, host_semaphore:
            return await fetch()

    async def _fetch_robots(
        self,
        entry: CrawlEntry,
        robots_url: str,
        fetch_hop: Callable | None = None,
    ) -> FetchedResponse:
        last_error: Exception | None = None
        response: FetchedResponse | None = None
        hop = fetch_hop or self._fetch_hop
        for attempt in range(self.config.retries + 1):
            try:
                async with asyncio.timeout(DEFAULT_TIMEOUT_MS / 1000):
                    response, _ = await fetch_with_validated_redirects(
                        robots_url,
                        lambda url, init, address: hop(
                            entry,
                            url,
                            init,
                            address,
                            body_limit=self.config.max_html_bytes,
                        ),
                        self.resolver,
                        self.config.max_html_bytes,
                    )
                if response.status != 429 and response.status < 500:
                    return response
                last_error = None
                if attempt < self.config.retries:
                    retry_after = response.headers.get("retry-after", "0")
                    try:
                        await self.sleep(max(0, float(retry_after)))
                    except ValueError:
                        await self.sleep(0)
            except (IntelError, OSError, TimeoutError) as error:
                last_error = error
                if isinstance(error, IntelError) and error.code in {
                    "CRAWL_LIMIT",
                    "RESPONSE_TOO_LARGE",
                    "UNSAFE_URL",
                }:
                    raise
                if attempt < self.config.retries:
                    await self.sleep(0)
        if response is not None:
            return response
        if last_error is not None:
            raise last_error
        raise IntelError("NETWORK_ERROR", "robots.txt fetch failed")

    async def _ensure_robots(
        self,
        entry: CrawlEntry,
        url: str,
        fetch: RobotsFetch | None = None,
    ) -> None:
        if not self.config.obey_robots:
            return
        allowed = (
            await self.robots_allowed(url)
            if self.robots_allowed is not None
            else await self._default_robots_allowed(entry, url, fetch)
        )
        if not allowed:
            raise IntelError("ROBOTS_DISALLOWED", "blocked by robots.txt")

    async def _default_robots_allowed(
        self,
        entry: CrawlEntry,
        url: str,
        fetch: RobotsFetch | None = None,
    ) -> bool:
        if self.robots_policy is None:
            raise RuntimeError("default robots policy is unavailable")
        return await self.robots_policy.allowed(entry, url, fetch)

    async def _extract(self, raw: bytes, mime_type: str, url: str):
        cancellation_event = threading.Event()
        extraction = asyncio.create_task(
            asyncio.to_thread(
                extract_resource,
                raw,
                mime_type,
                url,
                ocr_languages=self.config.ocr_languages,
                whisper_model=self.config.whisper_model,
                relevance_terms=self.relevance_terms,
                cancellation_event=cancellation_event,
            )
        )
        try:
            return await asyncio.shield(extraction)
        except asyncio.CancelledError:
            cancellation_event.set()
            with suppress(Exception):
                await extraction
            raise

    async def _render(self, entry: CrawlEntry, url: str):
        if self.renderer is None:
            raise IntelError(
                "BROWSER_UNAVAILABLE", "browser fallback disabled"
            )
        hostname = urlparse(url).hostname or ""
        host_semaphore = self.host_semaphores.setdefault(
            hostname, asyncio.Semaphore(self.config.per_host_concurrency)
        )
        async with host_semaphore:
            await self.rate_limit(hostname)
            async with self.byte_lock:
                remaining = (
                    self.config.max_total_bytes
                    - self.snapshot.downloaded_bytes
                )
                if remaining <= 0:
                    raise IntelError(
                        "RENDER_LIMIT", "crawl byte limit reached"
                    )
                observed = 0
                charged = 0

                def charge(downloaded: int) -> None:
                    nonlocal observed, charged
                    observed += downloaded
                    available = (
                        self.config.max_total_bytes
                        - self.snapshot.downloaded_bytes
                    )
                    amount = min(downloaded, max(0, available))
                    entry.downloaded_bytes += amount
                    self.snapshot.downloaded_bytes += amount
                    charged += amount
                    if amount < downloaded:
                        raise IntelError(
                            "RENDER_LIMIT", "crawl byte limit reached"
                        )

                async def fetch_robots(
                    robots_entry: CrawlEntry, robots_url: str
                ) -> FetchedResponse:
                    async def hop(
                        hop_entry,
                        hop_url,
                        init,
                        address,
                        *,
                        body_limit=None,
                    ):
                        return await self._fetch_hop_during_render(
                            hop_entry,
                            hop_url,
                            init,
                            address,
                            body_limit=body_limit,
                            held_hostname=hostname,
                        )

                    return await self._fetch_robots(
                        robots_entry, robots_url, hop
                    )

                async def before_navigation(target_url: str) -> None:
                    await self._ensure_robots(entry, target_url, fetch_robots)

                try:
                    rendered = await self.renderer(
                        url, remaining, before_navigation, charge
                    )
                    charge(max(0, rendered.downloaded_bytes - observed))
                except asyncio.CancelledError:
                    if charged:
                        await asyncio.shield(self.persist())
                    raise
                except IntelError as error:
                    try:
                        charge(max(0, error.downloaded_bytes - observed))
                    except IntelError as limit_error:
                        error = limit_error
                    if charged:
                        await self.persist()
                    raise error
                if charged:
                    await self.persist()
                return rendered

    async def fetch(self, entry: CrawlEntry) -> list[str]:
        if self.snapshot.downloaded_bytes >= self.config.max_total_bytes:
            entry.status = "skipped_limit"
            entry.error = "crawl byte limit reached"
            entry.updated_at = utc_now()
            await self.persist()
            return []
        try:
            await self._ensure_robots(entry, entry.canonical_url)
        except IntelError as error:
            if error.code != "ROBOTS_DISALLOWED":
                raise
            entry.status = "skipped_robots"
            entry.error = str(error)
            entry.updated_at = utc_now()
            await self.persist()
            return []
        cached = _cached_entry(
            self.cwd, self.snapshot.task_id, entry.canonical_url
        )
        cached_document: IntelDocument | None = None
        if cached:
            cached_document = _load_cached_document(self.cwd, cached)
            age = datetime.now(UTC) - _parse_time(cached_document.collected_at)
            if age <= timedelta(hours=self.config.cache_ttl_hours):
                _copy_cache(entry, cached)
                await self.persist()
                return list(entry.outbound_links)
        async with self.global_semaphore:
            entry.status = "fetching"
            entry.updated_at = utc_now()
            await self.persist()
            headers: dict[str, str] = {}
            if (
                cached
                and cached_document is not None
                and cached_document.collection_method != "browser"
            ):
                if cached.validators.etag:
                    headers["If-None-Match"] = cached.validators.etag
                if cached.validators.last_modified:
                    headers["If-Modified-Since"] = (
                        cached.validators.last_modified
                    )
            response: FetchedResponse | None = None
            final_url: object = entry.canonical_url
            last_error: Exception | None = None
            for attempt in range(self.config.retries + 1):
                entry.attempts += 1
                response = None
                try:
                    async with asyncio.timeout(DEFAULT_TIMEOUT_MS / 1000):
                        (
                            response,
                            final_url,
                        ) = await fetch_with_validated_redirects(
                            entry.canonical_url,
                            lambda url, init, address: self._fetch_hop(
                                entry, url, init, address
                            ),
                            self.resolver,
                            self.config.max_attachment_bytes,
                            {"headers": headers},
                            before_fetch=lambda url: self._ensure_robots(
                                entry, url
                            ),
                        )
                    if response.status not in {429} and response.status < 500:
                        break
                    if (
                        self.snapshot.downloaded_bytes
                        >= self.config.max_total_bytes
                    ):
                        last_error = IntelError(
                            "CRAWL_LIMIT", "crawl byte limit reached"
                        )
                        response = None
                        break
                    if attempt < self.config.retries:
                        retry_after = response.headers.get("retry-after", "0")
                        try:
                            await self.sleep(max(0, float(retry_after)))
                        except ValueError:
                            await self.sleep(0)
                except (TimeoutError, OSError, IntelError) as error:
                    last_error = error
                    if isinstance(
                        last_error, IntelError
                    ) and last_error.code in {
                        "CRAWL_LIMIT",
                        "RESPONSE_TOO_LARGE",
                        "ROBOTS_DISALLOWED",
                        "UNSAFE_URL",
                    }:
                        break
                    if attempt < self.config.retries:
                        await self.sleep(0)
            if response is None:
                if (
                    isinstance(last_error, IntelError)
                    and last_error.code == "ROBOTS_DISALLOWED"
                ):
                    entry.status = "skipped_robots"
                    entry.error = str(last_error)
                    entry.updated_at = utc_now()
                    await self.persist()
                    return []
                if isinstance(last_error, IntelError) and last_error.code in {
                    "CRAWL_LIMIT",
                    "RESPONSE_TOO_LARGE",
                }:
                    entry.status = "skipped_limit"
                    entry.error = str(last_error)
                    entry.updated_at = utc_now()
                    await self.persist()
                    return []
                code = (
                    f"{last_error.code}: "
                    if isinstance(last_error, IntelError)
                    else ""
                )
                entry.status = "failed"
                entry.error = f"{code}{last_error or 'fetch failed'}"
                entry.updated_at = utc_now()
                await self.persist()
                return []
            if (
                response.status == 304
                and cached
                and cached_document is not None
                and cached_document.collection_method != "browser"
            ):
                _load_cached_document(self.cwd, cached)
                _copy_cache(entry, cached)
                await self.persist()
                return list(entry.outbound_links)
            if 400 <= response.status < 500:
                entry.status = "skipped_http"
                entry.error = f"HTTP {response.status}"
                entry.updated_at = utc_now()
                await self.persist()
                return []
            if response.status != 200:
                entry.status = "failed"
                entry.error = f"HTTP {response.status}"
                entry.updated_at = utc_now()
                await self.persist()
                return []
            geturl = getattr(final_url, "geturl", None)
            final_url_string = str(geturl()) if geturl else str(final_url)
            mime_type = response.headers.get("content-type", "").split(";", 1)[
                0
            ]
            if not mime_type:
                mime_type = mimetypes.guess_type(final_url_string)[0] or ""
            entry.mime_type = mime_type
            entry.size = len(response.body)
            entry.validators = CrawlValidators(
                etag=response.headers.get("etag"),
                last_modified=response.headers.get("last-modified"),
            )
            is_html = mime_type in {"text/html", "application/xhtml+xml"}
            resource_limit = (
                self.config.max_html_bytes
                if is_html
                else self.config.max_attachment_bytes
            )
            if len(response.body) > resource_limit:
                entry.status = "skipped_limit"
                entry.error = "resource byte limit reached"
                entry.updated_at = utc_now()
                await self.persist()
                return []
            if is_rejected_resource(mime_type, final_url_string) or not (
                is_supported_resource(mime_type, final_url_string)
            ):
                entry.status = "skipped_unsupported"
                entry.error = "unsupported resource type"
                entry.extraction = ExtractionState(
                    status="skipped", error=entry.error
                )
                entry.updated_at = utc_now()
                await self.persist()
                return []
            extracted = await self._extract(
                response.body, mime_type, final_url_string
            )
            raw_final_url = final_url_string
            rendered_html: str | None = None
            rendered_url: str | None = None
            render_limited = False
            if is_html:
                static_html = decode_body(response.body, mime_type)
                entry.render_reason = should_render_html(
                    static_html, extracted.text
                )
                if entry.render_reason is not None:
                    try:
                        rendered = await self._render(entry, final_url_string)
                    except IntelError as error:
                        entry.render_error = f"{error.code}: {error}"
                        render_limited = error.code == "RENDER_LIMIT"
                        extracted = extracted.model_copy(
                            update={
                                "status": "unavailable",
                                "error": entry.render_error,
                            }
                        )
                    else:
                        rendered_html = rendered.html
                        rendered_url = rendered.final_url
                        extracted = await self._extract(
                            rendered.html.encode("utf-8"),
                            "text/html",
                            rendered_url,
                        )
                        if extracted.status == "complete":
                            extracted = extracted.model_copy(
                                update={"processor": "html-browser"}
                            )
                        else:
                            entry.render_error = (
                                extracted.error
                                or "RENDER_EMPTY: rendered page has no text"
                            )
            document = archive_document(
                self.cwd,
                entry.canonical_url,
                raw_final_url,
                mime_type,
                response.body,
                extracted.text,
                "failed"
                if extracted.status == "skipped"
                else extracted.status,
                rendered_html=rendered_html,
                rendered_url=rendered_url,
                render_error=entry.render_error,
                title=extracted.title,
                publish_time=extracted.publish_time,
                publish_time_source=extracted.publish_time_source,
            )
            entry.canonical_url = document.canonical_url
            entry.document_id = document.id
            entry.status = "skipped_limit" if render_limited else "complete"
            entry.extraction = ExtractionState(
                status=extracted.status,
                processor=extracted.processor,
                text_path=document.text_path,
                error=extracted.error,
            )
            entry.outbound_links = list(extracted.links)
            entry.outbound_relevance = dict(extracted.link_relevance)
            entry.updated_at = utc_now()
            await self.persist()
            return extracted.links


async def crawl_collect(
    cwd: Path,
    task_id: str,
    seeds: list[str] | None = None,
    *,
    config: CrawlConfig | None = None,
    fetcher: FetchLike | None = None,
    resolver: AddressResolver | None = None,
    robots_allowed: RobotsAllowed | None = None,
    sleep: Sleep = asyncio.sleep,
    on_event: CrawlEventCallback | None = None,
    renderer: BrowserRender | None = None,
) -> CrawlSnapshot:
    """Run or resume a task crawl without consuming the agent fetch budget."""
    seeds = seeds or []
    if config is None:
        try:
            config = CrawlConfig.model_validate(
                load_crawl(cwd, task_id).config
            )
        except IntelError as error:
            if error.code != "NOT_FOUND":
                raise
            config = CrawlConfig()
    snapshot = create_crawl(cwd, task_id, seeds, config)
    try:
        task = load_task(cwd, task_id)
        relevance_terms = relevance_tokens(
            " ".join(
                [task.topic, *(question.text for question in task.questions)]
            )
        )
    except IntelError as error:
        if error.code != "NOT_FOUND":
            raise
        relevance_terms = []
    if fetcher is None:

        async def default_fetcher(
            url: str, init: dict | None, address: str
        ) -> FetchedResponse:
            limits = init or {}
            return await pinned_fetch(
                url,
                init,
                address,
                int(
                    limits.get("_max_body_bytes", config.max_attachment_bytes)
                ),
                int(limits.get("_max_html_bytes", config.max_html_bytes)),
                limits.get("_body_progress"),
            )

        fetcher = default_fetcher

    runner = _CrawlRunner(
        cwd,
        snapshot,
        config,
        fetcher,
        resolver,
        robots_allowed,
        sleep,
        on_event,
        relevance_terms,
        renderer,
    )
    if on_event is not None:
        await on_event(
            CrawlEvent("crawl.started", _crawl_event_data(snapshot))
        )
    try:
        while queued := [
            entry for entry in snapshot.entries if entry.status == "queued"
        ]:
            batch = sorted(
                queued, key=lambda item: (item.priority, item.created_at)
            )[: config.concurrency]
            link_groups = await asyncio.gather(
                *(runner.fetch(entry) for entry in batch)
            )
            _deduplicate_entries(snapshot)
            for parent, links in zip(batch, link_groups, strict=True):
                for link in links:
                    source_priority = (
                        1
                        if (urlparse(link).hostname or "").endswith(
                            (".gov", ".gov.cn")
                        )
                        else 0
                    )
                    enqueue_url(
                        snapshot,
                        link,
                        parent_url=parent.canonical_url,
                        depth=parent.depth + 1,
                        relevance=parent.outbound_relevance.get(link, 0),
                        source_priority=source_priority,
                    )
            await runner.persist()
    except asyncio.CancelledError:
        for entry in snapshot.entries:
            if entry.status == "fetching":
                entry.status = "queued"
                entry.updated_at = utc_now()
        snapshot.status = "paused"
        await runner.persist()
        raise
    snapshot.status = "complete"
    await runner.persist()
    if on_event is not None:
        await on_event(
            CrawlEvent("crawl.completed", _crawl_event_data(snapshot))
        )
    return snapshot
