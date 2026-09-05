"""Playwright browser fetcher: render and snapshot (spec §7.1)."""

from __future__ import annotations

from datetime import UTC, datetime
from time import monotonic

from ..contracts.errors import DomainError
from ..contracts.resources import FetchResult, ResourceOrigin
from .security import validate_public_url


class BrowserFetcher:
    """Renders a page and snapshots the resulting DOM as a resource.

    Egress isolation is not implemented here; a real deployment must route
    browser traffic through a controlled proxy (spec §7.2). This fetcher only
    performs render-and-snapshot and does not claim network isolation.
    """

    def __init__(self, resource_store) -> None:
        self.resource_store = resource_store
        self._browser = None

    def availability(self) -> str:
        try:
            from playwright.async_api import async_playwright  # noqa: F401
        except ImportError:
            return "missing_dependency"
        return "available"

    async def fetch(self, request) -> FetchResult:
        await validate_public_url(request.url)
        from playwright.async_api import async_playwright

        start = monotonic()
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                try:
                    await page.goto(
                        request.url,
                        wait_until="networkidle",
                        timeout=request.timeout_seconds * 1000,
                    )
                except Exception as error:  # noqa: BLE001
                    raise DomainError(
                        "BLOCKED",
                        f"browser could not render {request.url}: {error}",
                        stage="fetch",
                    ) from error
                html = await page.content()
                final_url = page.url
            finally:
                await browser.close()

        async def chunks():
            data = html.encode("utf-8")
            for i in range(0, len(data), 64 * 1024):
                yield data[i : i + 64 * 1024]

        resource = await self.resource_store.write_stream(
            chunks(),
            origin=ResourceOrigin(
                requested_url=request.url,
                final_url=final_url,
                acquired_at=datetime.now(UTC),
            ),
            media_type="text/html",
            max_bytes=request.max_bytes,
        )
        return FetchResult(
            resource=resource,
            status_code=200,
            method="browser",
            elapsed_ms=int((monotonic() - start) * 1000),
        )
