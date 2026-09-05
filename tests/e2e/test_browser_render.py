"""Browser render end-to-end (spec A07; egress isolation unverified)."""

from __future__ import annotations

import pytest

from intel_agent.contracts.resources import FetchRequest
from intel_agent.fetch.browser import BrowserFetcher

# A real static public page that renders without JavaScript; used to prove
# the browser fetcher returns a rendered HTML snapshot.
_REAL_URL = "https://example.com/"


@pytest.mark.real_backend
async def test_browser_renders_real_page(harness):
    fetcher = BrowserFetcher(harness.resource_store)
    if fetcher.availability() != "available":
        pytest.skip("playwright not available")
    result = await fetcher.fetch(
        FetchRequest(url=_REAL_URL, mode="browser", timeout_seconds=30)
    )
    assert result.method == "browser"
    assert result.resource.media_type == "text/html"
    with harness.resource_store.open(result.resource.resource_id) as fh:
        html = fh.read().decode("utf-8", errors="replace")
    assert "<html" in html.lower()
