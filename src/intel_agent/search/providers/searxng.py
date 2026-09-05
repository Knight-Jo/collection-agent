"""SearXNG provider adapter (spec §6)."""

from __future__ import annotations

import json
from datetime import datetime

import httpx

from ...contracts.ports import (
    FilterCapability,
    ProviderCapabilities,
)
from ...contracts.research import SearchHit, SearchQuery
from .._util import make_hit


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class SearXNGProvider:
    name = "searxng"

    def __init__(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.client = client
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            source_types=["web"],
            dates=FilterCapability(supported=False, reliable_postfilter=True),
            language=FilterCapability(supported=True),
            domains=FilterCapability(supported=True),
            exclude_domains=FilterCapability(supported=True),
        )

    async def search(self, query: SearchQuery, limit: int) -> list[SearchHit]:
        params: dict[str, str | int] = {
            "q": query.text,
            "format": "json",
            "safesearch": "0",
        }
        if query.language:
            params["language"] = query.language
        if query.domains:
            params["q"] = (
                query.text + " " + " ".join(f"site:{d}" for d in query.domains)
            )
        response = await self.client.get(
            f"{self.base_url}/search",
            params=params,
            headers={"Accept": "application/json"},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        data = json.loads(response.text)
        out: list[SearchHit] = []
        for rank, result in enumerate(data.get("results", []), start=1):
            hit = make_hit(
                "searxng",
                query,
                result.get("url", ""),
                title=result.get("title"),
                snippet=(result.get("content") or "")[:400],
                published_at=_parse_date(result.get("publishedDate")),
                source_types=["web"],
                rank=rank,
                score=None,
            )
            out.append(hit)
            if len(out) >= limit:
                break
        return out
