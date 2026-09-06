"""OpenAlex API provider (academic, optional key)."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx2

from ...contracts.ports import (
    FilterCapability,
    ProviderCapabilities,
)
from ...contracts.research import SearchHit, SearchQuery
from .._util import make_hit


class OpenAlexProvider:
    name = "openalex"

    def __init__(
        self,
        client: httpx2.AsyncClient,
        base_url: str = "https://api.openalex.org/works",
        api_key: str | None = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.client = client
        self.base_url = base_url
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            source_types=["academic"],
            dates=FilterCapability(supported=True),
            language=FilterCapability(supported=False),
            domains=FilterCapability(supported=False),
            exclude_domains=FilterCapability(supported=False),
        )

    async def search(self, query: SearchQuery, limit: int) -> list[SearchHit]:
        params: dict[str, str | int] = {
            "search": query.text,
            "per-page": limit,
        }
        if query.start_date:
            params["filter"] = f"from_publication_date:{query.start_date}"
        if query.end_date:
            params["filter"] = (
                f"{params.get('filter', '')},"
                f"to_publication_date:{query.end_date}"
            )
        headers = {}
        if self.api_key:
            params["api_key"] = self.api_key
        response = await self.client.get(
            self.base_url,
            params=params,
            headers=headers,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        out: list[SearchHit] = []
        for rank, work in enumerate(data.get("results", []), start=1):
            published_at = None
            if work.get("publication_date"):
                try:
                    published_at = datetime.fromisoformat(
                        work["publication_date"]
                    ).replace(tzinfo=UTC)
                except ValueError:
                    published_at = None
            snippet = None
            abstract = work.get("abstract_inverted_index")
            if abstract is not None and isinstance(abstract, dict):
                snippet = _reconstruct_abstract(abstract)[:400] or None
            hit = make_hit(
                "openalex",
                query,
                work.get("doi") or work.get("id", ""),
                title=work.get("title"),
                snippet=snippet,
                published_at=published_at,
                source_types=["academic"],
                rank=rank,
                score=work.get("relevance_score"),
            )
            out.append(hit)
        return out


def _reconstruct_abstract(inverted: dict) -> str:
    positions: dict[int, str] = {}
    for word, indices in inverted.items():
        for index in indices:
            positions[index] = word
    return " ".join(positions[i] for i in sorted(positions))
