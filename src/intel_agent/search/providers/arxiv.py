"""arXiv export API provider (academic)."""

from __future__ import annotations

import asyncio
import xml.etree.ElementTree as ET
from datetime import datetime
from time import monotonic

import httpx

from ...contracts.ports import (
    FilterCapability,
    ProviderCapabilities,
)
from ...contracts.research import SearchHit, SearchQuery
from .._util import make_hit

_ATOM = "{http://www.w3.org/2005/Atom}"


def _arxiv_date(query: SearchQuery) -> str | None:
    if query.start_date and query.end_date:
        return (
            f"{query.start_date.isoformat()} TO {query.end_date.isoformat()}"
        )
    if query.start_date:
        return f"{query.start_date.isoformat()} TO 9999-12-31"
    if query.end_date:
        return f"0000-01-01 TO {query.end_date.isoformat()}"
    return None


def _https(url: str) -> str:
    # arXiv Atom <id> uses http://, but port 80 is not served; upgrade to
    # https so downstream fetch actually reaches the source.
    return url.replace("http://", "https://", 1)


class ArxivProvider:
    name = "arxiv"

    def __init__(
        self,
        client: httpx.AsyncClient,
        base_url: str = "https://export.arxiv.org/api/query",
        timeout_seconds: float = 20.0,
        min_interval: float = 3.0,
    ) -> None:
        self.client = client
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.min_interval = min_interval
        self._last_call = 0.0

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            source_types=["academic"],
            dates=FilterCapability(supported=True),
            language=FilterCapability(supported=False),
            domains=FilterCapability(supported=False),
            exclude_domains=FilterCapability(supported=False),
        )

    async def search(self, query: SearchQuery, limit: int) -> list[SearchHit]:
        wait = self.min_interval - (monotonic() - self._last_call)
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_call = monotonic()
        search_query = f"all:{query.text}"
        date_range = _arxiv_date(query)
        if date_range:
            search_query += f" AND submittedDate:[{date_range}]"
        response = await self.client.get(
            self.base_url,
            params={
                "search_query": search_query,
                "start": 0,
                "max_results": limit,
                "sortBy": "relevance",
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        root = ET.fromstring(response.text)
        out: list[SearchHit] = []
        for rank, entry in enumerate(root.findall(f"{_ATOM}entry"), start=1):
            published = entry.findtext(f"{_ATOM}published")
            published_at = None
            if published:
                try:
                    published_at = datetime.fromisoformat(
                        published.replace("Z", "+00:00")
                    )
                except ValueError:
                    published_at = None
            hit = make_hit(
                "arxiv",
                query,
                _https((entry.findtext(f"{_ATOM}id") or "").strip()),
                title=(entry.findtext(f"{_ATOM}title") or "").strip(),
                snippet=(entry.findtext(f"{_ATOM}summary") or "").strip()[
                    :400
                ],
                published_at=published_at,
                source_types=["academic"],
                rank=rank,
                score=None,
            )
            out.append(hit)
            if len(out) >= limit:
                break
        return out
