"""Tavily search provider (returns clean content)."""

from __future__ import annotations

from datetime import datetime

import httpx2

from ...contracts.ports import (
    FilterCapability,
    ProviderCapabilities,
)
from ...contracts.research import SearchHit, SearchQuery
from .._util import make_hit


class TavilyProvider:
    name = "tavily"

    def __init__(
        self,
        client: httpx2.AsyncClient,
        api_key: str | None = None,
        base_url: str = "https://api.tavily.com/search",
        search_depth: str = "advanced",
        max_results: int = 10,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.client = client
        self.api_key = api_key
        self.base_url = base_url
        self.search_depth = search_depth
        self.max_results = max_results
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
        body: dict = {
            "query": query.text,
            "search_depth": self.search_depth,
            "max_results": min(limit, self.max_results),
        }
        if self.api_key:
            body["api_key"] = self.api_key
        response = await self.client.post(
            self.base_url,
            json=body,
            headers={"Content-Type": "application/json"},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        out: list[SearchHit] = []
        for rank, result in enumerate(data.get("results", []), start=1):
            published_at = None
            if result.get("published_date"):
                try:
                    published_at = datetime.fromisoformat(
                        result["published_date"].replace("Z", "+00:00")
                    )
                except ValueError:
                    published_at = None
            content = result.get("content") or None
            hit = make_hit(
                "tavily",
                query,
                result.get("url", ""),
                title=result.get("title"),
                snippet=(content or "")[:400] or None,
                published_at=published_at,
                source_types=["web"],
                rank=rank,
                score=result.get("score"),
                content=content,
            )
            out.append(hit)
            if len(out) >= limit:
                break
        return out
