"""Brave Search API provider (URL + snippet, no full content)."""

from __future__ import annotations

import httpx

from ...contracts.ports import (
    FilterCapability,
    ProviderCapabilities,
)
from ...contracts.research import SearchHit, SearchQuery
from .._util import make_hit


class BraveProvider:
    name = "brave"

    def __init__(
        self,
        client: httpx.AsyncClient,
        api_key: str | None = None,
        base_url: str = "https://api.search.brave.com/res/v1/web/search",
        timeout_seconds: float = 20.0,
    ) -> None:
        self.client = client
        self.api_key = api_key
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            source_types=["web"],
            dates=FilterCapability(supported=False),
            language=FilterCapability(supported=False),
            domains=FilterCapability(supported=False),
            exclude_domains=FilterCapability(supported=False),
        )

    async def search(self, query: SearchQuery, limit: int) -> list[SearchHit]:
        headers = {}
        if self.api_key:
            headers["X-Subscription-Token"] = self.api_key
        response = await self.client.get(
            self.base_url,
            params={"q": query.text, "count": limit},
            headers=headers,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        out: list[SearchHit] = []
        for rank, result in enumerate(
            data.get("web", {}).get("results", []), start=1
        ):
            snippet = result.get("description") or None
            hit = make_hit(
                "brave",
                query,
                result.get("url", ""),
                title=result.get("title"),
                snippet=(snippet or "")[:400] or None,
                published_at=None,
                source_types=["web"],
                rank=rank,
                score=None,
            )
            out.append(hit)
            if len(out) >= limit:
                break
        return out
