"""Persistent, task-owned crawl frontier using the DNS-pinned fetch path."""

from __future__ import annotations

import asyncio
import mimetypes
import threading
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from .config import CrawlConfig
from .extract import (
    extract_resource,
    is_rejected_resource,
    is_supported_resource,
)
from .fetch import (
    DEFAULT_TIMEOUT_MS,
    REDIRECT_STATUSES,
    USER_AGENT,
    FetchedResponse,
    FetchLike,
    canonicalize_url,
    fetch_with_validated_redirects,
    injection_warnings,
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
from .security import AddressResolver, source_group_of
from .source import source_type_for_domain
from .storage import (
    intel_path,
    list_crawls,
    load_crawl,
    read_json,
    save_crawl,
    sha256,
    verify_document_integrity,
    write_file_atomic,
    write_json_atomic,
)

RobotsAllowed = Callable[[str], Awaitable[bool]]
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


def _priority(
    depth: int,
    relevance: float,
    source_priority: float,
    attachment: bool,
) -> float:
    return depth * 100 - relevance * 20 - source_priority * 10 - attachment * 5


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
    if depth > config.max_depth or len(snapshot.entries) >= config.max_urls:
        return False
    canonical = canonicalize_url(raw_url)
    if any(entry.canonical_url == canonical for entry in snapshot.entries):
        return False
    if attachment is None:
        attachment = Path(urlparse(canonical).path).suffix.lower() in (
            _ATTACHMENT_SUFFIXES
        )
    now = utc_now()
    snapshot.entries.append(
        CrawlEntry(
            canonical_url=canonical,
            parent_url=(canonicalize_url(parent_url) if parent_url else None),
            depth=depth,
            priority=_priority(
                depth, relevance, source_priority, bool(attachment)
            ),
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
        enqueue_url(snapshot, seed, parent_url=None, depth=0)
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


def _archive_resource(
    cwd: Path,
    requested_url: str,
    final_url: str,
    mime_type: str,
    raw: bytes,
    text: str,
    extraction_status: Literal["complete", "unavailable", "failed"],
) -> IntelDocument:
    canonical_url = canonicalize_url(final_url)
    raw_hash = sha256(raw)
    document_id = f"doc-{sha256(f'{canonical_url}\n{raw_hash}')[:16]}"
    record_path = f"documents/{document_id}.json"
    if intel_path(cwd, record_path).exists():
        document = IntelDocument.model_validate(read_json(cwd, record_path))
        verify_document_integrity(cwd, document)
        if (
            extraction_status == "complete"
            and document.extraction_status != "complete"
        ):
            text_hash = sha256(text)
            text_path = f"data/raw/{document_id}.{text_hash[:16]}.txt"
            write_file_atomic(cwd, text_path, text)
            document = document.model_copy(
                update={
                    "text_path": text_path,
                    "text_sha256": text_hash,
                    "extraction_status": "complete",
                }
            )
            write_json_atomic(cwd, record_path, document.model_dump())
        return document
    raw_path = f"data/raw/{document_id}.raw"
    text_path = f"data/raw/{document_id}.txt"
    write_file_atomic(cwd, raw_path, raw)
    write_file_atomic(cwd, text_path, text)
    hostname = urlparse(final_url).hostname or ""
    try:
        source_group = source_group_of(final_url)
    except IntelError:
        source_group = hostname.lower()
    document = IntelDocument(
        id=document_id,
        requested_url=requested_url,
        final_url=final_url,
        canonical_url=canonical_url,
        title=Path(urlparse(final_url).path).name or final_url,
        content_type=mime_type,
        collected_at=utc_now(),
        source_type=source_type_for_domain(hostname),
        source_group=source_group,
        raw_path=raw_path,
        raw_sha256=raw_hash,
        text_path=text_path,
        text_sha256=sha256(text),
        extraction_status=extraction_status,
        injection_warnings=injection_warnings(text),
    )
    write_json_atomic(cwd, record_path, document.model_dump())
    return document


class _RobotsPolicy:
    def __init__(
        self,
        fetcher: FetchLike,
        resolver: AddressResolver | None,
        max_bytes: int,
    ):
        self.fetcher = fetcher
        self.resolver = resolver
        self.max_bytes = max_bytes
        self.parsers: dict[str, RobotFileParser | None] = {}
        self.locks: dict[str, asyncio.Lock] = {}

    async def allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        async with self.locks.setdefault(origin, asyncio.Lock()):
            if origin not in self.parsers:
                self.parsers[origin] = await self._load(origin)
        parser = self.parsers[origin]
        return True if parser is None else parser.can_fetch(USER_AGENT, url)

    async def _load(self, origin: str) -> RobotFileParser | None:
        robots_url = f"{origin}/robots.txt"
        try:
            response, _ = await fetch_with_validated_redirects(
                robots_url, self.fetcher, self.resolver, self.max_bytes
            )
        except (IntelError, TimeoutError):
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
        robots_allowed: RobotsAllowed,
        sleep: Sleep,
        on_event: CrawlEventCallback | None,
    ):
        self.cwd = cwd
        self.snapshot = snapshot
        self.config = config
        self.fetcher = fetcher
        self.resolver = resolver
        self.robots_allowed = robots_allowed
        self.sleep = sleep
        self.on_event = on_event
        self.global_semaphore = asyncio.Semaphore(config.concurrency)
        self.host_semaphores: dict[str, asyncio.Semaphore] = {}
        self.host_locks: dict[str, asyncio.Lock] = {}
        self.host_last_start: dict[str, float] = {}
        self.persist_lock = asyncio.Lock()
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

    async def _account_download(
        self, entry: CrawlEntry, downloaded_bytes: int
    ) -> None:
        async with self.byte_lock:
            entry.downloaded_bytes += downloaded_bytes
            self.snapshot.downloaded_bytes += downloaded_bytes
            exceeded = (
                self.snapshot.downloaded_bytes > self.config.max_total_bytes
            )
        await self.persist()
        if exceeded:
            raise IntelError("CRAWL_LIMIT", "crawl byte limit reached")

    async def _fetch_hop(
        self,
        entry: CrawlEntry,
        url: str,
        request_init: dict | None,
        address: str,
    ) -> FetchedResponse:
        hostname = urlparse(url).hostname or ""
        host_semaphore = self.host_semaphores.setdefault(
            hostname, asyncio.Semaphore(self.config.per_host_concurrency)
        )
        async with host_semaphore:
            await self.rate_limit(hostname)
            response = await self.fetcher(url, request_init, address)
            await self._account_download(entry, len(response.body))
            if (
                response.status in REDIRECT_STATUSES
                and self.snapshot.downloaded_bytes
                >= self.config.max_total_bytes
            ):
                raise IntelError("CRAWL_LIMIT", "crawl byte limit reached")
        return response

    async def fetch(self, entry: CrawlEntry) -> list[str]:
        if self.snapshot.downloaded_bytes >= self.config.max_total_bytes:
            entry.status = "skipped_limit"
            entry.error = "crawl byte limit reached"
            entry.updated_at = utc_now()
            await self.persist()
            return []
        if self.config.obey_robots and not await self.robots_allowed(
            entry.canonical_url
        ):
            entry.status = "skipped_robots"
            entry.error = "blocked by robots.txt"
            entry.updated_at = utc_now()
            await self.persist()
            return []
        cached = _cached_entry(
            self.cwd, self.snapshot.task_id, entry.canonical_url
        )
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
            if cached:
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
                    if (
                        isinstance(error, IntelError)
                        and error.downloaded_bytes
                    ):
                        try:
                            await self._account_download(
                                entry, error.downloaded_bytes
                            )
                        except IntelError as limit_error:
                            last_error = limit_error
                    if isinstance(
                        last_error, IntelError
                    ) and last_error.code in {
                        "CRAWL_LIMIT",
                        "RESPONSE_TOO_LARGE",
                        "UNSAFE_URL",
                    }:
                        break
                    if attempt < self.config.retries:
                        await self.sleep(0)
            if response is None:
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
            if response.status == 304 and cached:
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
            cancellation_event = threading.Event()
            extraction = asyncio.create_task(
                asyncio.to_thread(
                    extract_resource,
                    response.body,
                    mime_type,
                    final_url_string,
                    ocr_languages=self.config.ocr_languages,
                    whisper_model=self.config.whisper_model,
                    cancellation_event=cancellation_event,
                )
            )
            try:
                extracted = await asyncio.shield(extraction)
            except asyncio.CancelledError:
                cancellation_event.set()
                await extraction
                raise
            document = _archive_resource(
                self.cwd,
                entry.canonical_url,
                final_url_string,
                mime_type,
                response.body,
                extracted.text,
                "failed"
                if extracted.status == "skipped"
                else extracted.status,
            )
            entry.canonical_url = document.canonical_url
            entry.document_id = document.id
            entry.status = "complete"
            entry.extraction = ExtractionState(
                status=extracted.status,
                processor=extracted.processor,
                text_path=document.text_path,
                error=extracted.error,
            )
            entry.outbound_links = list(extracted.links)
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
    fetcher = fetcher or (
        lambda url, init, address: pinned_fetch(
            url, init, address, config.max_attachment_bytes
        )
    )
    if robots_allowed is None:
        robots_allowed = _RobotsPolicy(
            fetcher, resolver, config.max_html_bytes
        ).allowed
    runner = _CrawlRunner(
        cwd,
        snapshot,
        config,
        fetcher,
        resolver,
        robots_allowed,
        sleep,
        on_event,
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
