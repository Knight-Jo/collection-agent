"""Watch-gate: cheap change detection ahead of the research loop.

Layers, cheapest first, each able to short-circuit the next:

- L0 conditional GET: send the stored validators (ETag / Last-Modified);
  a 304 answer proves the page is unchanged at request cost only.
- L1 byte hash: the fetched resource is content-addressed (SHA-256), so
  identical bytes imply an unchanged page without any parsing.
- L2 content hash: bytes churned but the extracted main content (template
  noise like ads or timestamps aside) serializes to the same digest.

Only when a page survives all three layers does the monitor pay for the
research loop. A gate failure is never treated as "no change": the run
falls through to the expensive path rather than skipping it.
"""

from __future__ import annotations

import hashlib
import logging
from collections import Counter
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from ..contracts.errors import DomainError
from ..contracts.resources import FetchRequest
from ..storage.monitoring import MonitoringStore
from .models import Monitor, WatchSourceState

logger = logging.getLogger("intel_agent.monitoring.gate")

GATE_CHANGED = "changed"
GATE_UNCHANGED = "unchanged"
GATE_CONTENT_UNCHANGED = "content_unchanged"
GATE_FAILED = "failed"


class WatchCheck(BaseModel):
    """Outcome of checking one watched URL."""

    url: str
    outcome: str
    etag: str | None = None
    last_modified: str | None = None
    byte_hash: str | None = None
    content_hash: str | None = None
    error_code: str | None = None


class GateResult(BaseModel):
    checks: list[WatchCheck] = Field(default_factory=list)

    @property
    def changed_urls(self) -> list[str]:
        return [c.url for c in self.checks if c.outcome == GATE_CHANGED]

    @property
    def should_skip_research(self) -> bool:
        """Skip only when every watched page was checked and none changed.

        An empty watch list cannot decide anything (the monitor relies on
        open research), and a failed check is not evidence of "no change".
        """
        if not self.checks:
            return False
        return not any(
            c.outcome in (GATE_CHANGED, GATE_FAILED) for c in self.checks
        )

    def counts_summary(self) -> str:
        """Machine-readable outcome counts, e.g. ``unchanged=2,changed=1``."""
        counts = Counter(c.outcome for c in self.checks)
        return ",".join(f"{k}={v}" for k, v in sorted(counts.items()))


class WatchGate:
    """Runs the L0/L1/L2 gates over a monitor's watched pages."""

    def __init__(
        self,
        fetch_service,
        extraction_service,
        store: MonitoringStore,
        *,
        profile_id: str = "html",
        timeout_seconds: float = 20.0,
        max_bytes: int | None = None,
    ) -> None:
        self.fetch_service = fetch_service
        self.extraction_service = extraction_service
        self.store = store
        self.profile_id = profile_id
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes

    async def check(self, monitor: Monitor) -> GateResult:
        checks = [
            await self._check_url(monitor.monitor_id, url)
            for url in monitor.websites
        ]
        return GateResult(checks=checks)

    async def _check_url(self, monitor_id: str, url: str) -> WatchCheck:
        previous = self.store.get_watch_source(monitor_id, url)
        try:
            result = await self.fetch_service.fetch(
                FetchRequest(
                    url=url,
                    etag=previous.etag if previous else None,
                    last_modified=previous.last_modified if previous else None,
                    timeout_seconds=self.timeout_seconds,
                    max_bytes=self.max_bytes,
                )
            )
            if result.not_modified or result.resource is None:
                check = WatchCheck(
                    url=url,
                    outcome=GATE_UNCHANGED,
                    etag=result.etag,
                    last_modified=result.last_modified,
                    byte_hash=previous.byte_hash if previous else None,
                    content_hash=previous.content_hash if previous else None,
                )
            else:
                check = await self._classify(
                    url,
                    result.resource,
                    result.etag,
                    result.last_modified,
                    previous,
                )
        except DomainError as error:
            logger.warning(
                "watch gate failed url=%s error=%s", url, error.code
            )
            check = WatchCheck(
                url=url, outcome=GATE_FAILED, error_code=error.code
            )
            if previous is not None:
                # Keep the validators and hashes from the last good check;
                # clobbering them would disable the conditional request.
                check = check.model_copy(
                    update={
                        "etag": previous.etag,
                        "last_modified": previous.last_modified,
                        "byte_hash": previous.byte_hash,
                        "content_hash": previous.content_hash,
                    }
                )
        self.store.save_watch_source(
            WatchSourceState(
                monitor_id=monitor_id,
                url=url,
                etag=check.etag,
                last_modified=check.last_modified,
                byte_hash=check.byte_hash,
                content_hash=check.content_hash,
                last_checked_at=datetime.now(UTC),
                last_outcome=check.outcome,
            )
        )
        return check

    async def _classify(self, url, resource, etag, last_modified, previous):
        byte_hash = resource.content_hash
        if previous is not None and previous.byte_hash == byte_hash:
            return WatchCheck(
                url=url,
                outcome=GATE_UNCHANGED,
                etag=etag,
                last_modified=last_modified,
                byte_hash=byte_hash,
                content_hash=previous.content_hash,
            )
        content_hash = await self._content_hash(resource)
        outcome = GATE_CHANGED
        if previous is not None and previous.content_hash == content_hash:
            outcome = GATE_CONTENT_UNCHANGED
        return WatchCheck(
            url=url,
            outcome=outcome,
            etag=etag,
            last_modified=last_modified,
            byte_hash=byte_hash,
            content_hash=content_hash,
        )

    async def _content_hash(self, resource) -> str:
        result = await self.extraction_service.extract(
            resource, self.profile_id
        )
        # Canonical form: block order preserved by the extractor, surrounding
        # whitespace stripped; volatile fields (timestamps, ids) are not part
        # of the block text.
        canonical = "\n".join(
            block.text.strip() for block in result.blocks if block.text.strip()
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
