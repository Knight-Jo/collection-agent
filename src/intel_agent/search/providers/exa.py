"""Exa neural-search provider (returns clean page text)."""

from __future__ import annotations

from datetime import datetime

import httpx

from ...contracts.ports import (
    FilterCapability,
    ProviderCapabilities,
)
from ...contracts.research import SearchHit, SearchQuery
from .._util import make_hit


class ExaProvider:
    name = "exa"

    def __init__(
        self,
        client: httpx.AsyncClient,
        api_key: str | None = None,
        base_url: str = "https://api.exa.ai/search",
        num_results: int = 10,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.client = client
        self.api_key = api_key
        self.base_url = base_url
        self.num_results = num_results
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
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        response = await self.client.post(
            self.base_url,
            headers=headers,
            json={
                "query": query.text,
                "num_results": min(limit, self.num_results),
                "type": "neural",
                "contents": {"text": True},
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        out: list[SearchHit] = []
        for rank, result in enumerate(data.get("results", []), start=1):
            published_at = None
            if result.get("publishedDate"):
                try:
                    published_at = datetime.fromisoformat(
                        result["publishedDate"].replace("Z", "+00:00")
                    )
                except ValueError:
                    published_at = None
            content = result.get("text") or None
            hit = make_hit(
                "exa",
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
