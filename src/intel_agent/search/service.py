"""Bounded multi-provider search service (spec §5, §6)."""

from __future__ import annotations

import asyncio
import logging
from time import monotonic

from ..contracts.errors import DomainError
from ..contracts.ports import SearchProvider
from ..contracts.research import (
    BatchStatus,
    ProviderReport,
    ProviderStatus,
    SearchBatch,
    SearchHit,
    SearchQuery,
    SearchRequest,
)
from ..runtime.config import SearchConfig
from ..runtime.limits import AttemptLedger
from ..runtime.logging import StructuredLogger

RRF_CONSTANT = 60

logger = logging.getLogger("intel_agent.search")


def rrf_score(ranks: list[int]) -> float:
    return sum(1.0 / (RRF_CONSTANT + rank) for rank in ranks)


class SearchService:
    """Search configured providers concurrently and combine their results.

    Each provider is bounded by the configured timeout and retry policy. The
    service filters invalid results, merges duplicate sources, ranks them with
    reciprocal rank fusion, and returns provider-level status reports.

    Attributes:
        providers: Search providers keyed by their public provider name.
        config: Search timeouts, retry counts, and result limits.
        attempts: Optional shared ledger for tracking search attempts.
        logger: Structured logger available to the search service.
    """

    def __init__(
        self,
        providers: list[SearchProvider],
        config: SearchConfig,
        attempts: AttemptLedger | None = None,
        logger: StructuredLogger | None = None,
    ) -> None:
        self.providers: dict[str, SearchProvider] = {
            p.name: p for p in providers
        }
        self.config = config
        self.attempts = attempts
        self.logger = logger or StructuredLogger()

    def replace_providers(self, providers: list[SearchProvider]) -> None:
        """Hot-swap the active providers (e.g. after a settings mutation)."""
        self.providers = {p.name: p for p in providers}

    async def search(self, request: SearchRequest) -> SearchBatch:
        """Run a bounded search across the requested providers.

        Unknown provider names are ignored; when no names are supplied, all
        configured providers are queried. Results are filtered, deduplicated,
        ranked, and limited before the batch status is returned.

        Args:
            request: Query, provider selection, and per-batch result limits.

        Returns:
            Search hits together with one status report per attempted provider.

        Raises:
            DomainError: If the request limits are invalid.
        """
        if request.per_provider_limit <= 0 or request.total_limit <= 0:
            raise DomainError("INVALID_REQUEST", "limits must be positive")
        requested = request.provider_names or list(self.providers)
        # Unknown provider names (e.g. a model emitting source-type labels)
        # are ignored rather than failing the whole batch.
        names = [n for n in requested if n in self.providers]
        if not names:
            names = list(self.providers)
        if not names:
            return SearchBatch(hits=[], provider_reports=[], status="failed")

        deadline = monotonic() + self.config.round_deadline_seconds
        reports: list[ProviderReport] = []
        merged: dict[str, SearchHit] = {}

        async def run_one(name: str) -> ProviderReport:
            provider = self.providers[name]
            cfg = self.config.providers.get(name)
            if cfg is not None and not cfg.enabled:
                return ProviderReport(
                    provider=name,
                    status="disabled",
                    elapsed_ms=0,
                    returned_count=0,
                )
            start = monotonic()
            try:
                hits = await self._call_with_retry(
                    provider,
                    request.query,
                    request.per_provider_limit,
                    deadline,
                )
                hits = [h for h in hits if self._post_filter(request.query, h)]
                self._merge(merged, hits)
                logger.debug(
                    "provider=%s query=%r hits=%d",
                    name,
                    request.query.text,
                    len(hits),
                )
                return ProviderReport(
                    provider=name,
                    status="success",
                    elapsed_ms=_elapsed(start),
                    returned_count=len(hits),
                )
            except DomainError as error:
                return ProviderReport(
                    provider=name,
                    status=_status_for(error),
                    elapsed_ms=_elapsed(start),
                    returned_count=0,
                    error=error.code,
                    warnings=[error.message],
                )
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001
                return ProviderReport(
                    provider=name,
                    status="failed",
                    elapsed_ms=_elapsed(start),
                    returned_count=0,
                    error="UNKNOWN",
                    warnings=[str(error)],
                )

        # Run providers concurrently, then collect completed and timed-out work.
        calls = {name: asyncio.create_task(run_one(name)) for name in names}
        done, pending = await asyncio.wait(
            calls.values(),
            timeout=max(0.0, deadline - monotonic()),
        )
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        for name, task in calls.items():
            if task in pending:
                reports.append(
                    ProviderReport(
                        provider=name,
                        status="timeout",
                        elapsed_ms=_elapsed(monotonic()),
                        returned_count=0,
                        error="TIMEOUT",
                    )
                )
            else:
                reports.append(task.result())

        # Merge duplicate hits and rank sources by their provider positions.
        hits = sorted(
            merged.values(),
            key=lambda h: (-rrf_score(_ranks(h)), h.dedup_key),
        )[: request.total_limit]
        status = _batch_status(reports)
        logger.debug(
            "search query=%r status=%s hits=%d",
            request.query.text,
            status,
            len(hits),
        )
        return SearchBatch(hits=hits, provider_reports=reports, status=status)

    async def _call_with_retry(
        self,
        provider: SearchProvider,
        query: SearchQuery,
        limit: int,
        deadline: float,
    ) -> list[SearchHit]:
        attempts = self.config.provider_attempts
        for attempt in range(1, attempts + 1):
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise DomainError("TIMEOUT", "search deadline reached")
            try:
                return await asyncio.wait_for(
                    provider.search(query, limit),
                    timeout=min(
                        self.config.provider_timeout_seconds, remaining
                    ),
                )
            except TimeoutError:
                if attempt >= attempts:
                    raise DomainError(
                        "TIMEOUT", "provider timed out"
                    ) from None
            except DomainError as error:
                if not error.retryable or attempt >= attempts:
                    raise
        raise DomainError("TIMEOUT", "provider timed out")

    def _merge(
        self, merged: dict[str, SearchHit], hits: list[SearchHit]
    ) -> None:
        for hit in hits:
            existing = merged.get(hit.dedup_key)
            if existing is None:
                merged[hit.dedup_key] = hit
            else:
                existing.occurrences.extend(hit.occurrences)

    @staticmethod
    def _post_filter(query: SearchQuery, hit: SearchHit) -> bool:
        host = _host_of(hit.url)
        if query.start_date is not None or query.end_date is not None:
            if hit.published_at is None:
                return False
            date = hit.published_at.date()
            if query.start_date is not None and date < query.start_date:
                return False
            if query.end_date is not None and date > query.end_date:
                return False
        if query.domains and not any(
            _host_matches(host, d) for d in query.domains
        ):
            return False
        return not any(_host_matches(host, d) for d in query.exclude_domains)


def _host_of(url: str) -> str:
    from urllib.parse import urlsplit

    return (urlsplit(url).hostname or "").lower()


def _host_matches(host: str, domain: str) -> bool:
    domain = domain.lower()
    return host == domain or host.endswith("." + domain)


def _ranks(hit: SearchHit) -> list[int]:
    return [occ.provider_rank or 1 for occ in hit.occurrences]


def _status_for(error: DomainError) -> ProviderStatus:
    return "timeout" if error.code == "TIMEOUT" else "failed"


def _batch_status(reports: list[ProviderReport]) -> BatchStatus:
    statuses = {r.status for r in reports}
    if not reports:
        return "failed"
    if all(s == "disabled" for s in statuses):
        return "failed"
    if any(s == "failed" for s in statuses) and not any(
        s == "success" for s in statuses
    ):
        return "failed"
    if statuses <= {"success"} or (
        "success" in statuses and "disabled" in statuses
    ):
        return "success"
    return "partial"


def _elapsed(start: float) -> int:
    return int((monotonic() - start) * 1000)
