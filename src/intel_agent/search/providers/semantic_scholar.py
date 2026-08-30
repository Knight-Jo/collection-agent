"""Semantic Scholar public Graph API: anonymous enhancement source.

Shares a rate-limited pool with other anonymous consumers; on 429 the
capability simply degrades (it is a supplement, not a dependency).
"""

from __future__ import annotations

from .. import SearchResult, _provider_result
from ..provider import (
    ProviderMetadata,
    SearchRequest,
    rate_limit,
    validate_public_provider,
)

_S2_API = "https://api.semanticscholar.org/graph/v1/paper/search"


class SemanticScholarProvider:
    metadata = ProviderMetadata(
        name="semantic_scholar",
        access_mode="OPEN_ANONYMOUS",
        supports_anonymous=True,
    )

    def __init__(
        self,
        *,
        base_url: str = _S2_API,
        min_interval: float = 1.5,
        max_results: int = 10,
    ) -> None:
        self.base_url = base_url
        self.min_interval = min_interval
        self.max_results = max_results
        self.last_calls = 0

    async def search(
        self, client, request: SearchRequest
    ) -> list[SearchResult]:
        await rate_limit(self.metadata.name, self.min_interval)
        self.last_calls = 1
        res = await client.get(
            self.base_url,
            params={
                "query": request.query,
                "limit": min(request.max_results, self.max_results),
                "fields": "title,url,abstract,authors,year,externalIds",
            },
        )
        if res.status_code == 429:
            self.last_calls = 0  # degraded, no usable call
            return []
        res.raise_for_status()
        data = res.json().get("data", [])
        out: list[SearchResult] = []
        for rank, item in enumerate(data):
            url = item.get("url") or ""
            if not url:
                doi = (item.get("externalIds") or {}).get("DOI")
                url = f"https://doi.org/{doi}" if doi else ""
            authors = [a.get("name", "") for a in item.get("authors", [])]
            result = _provider_result(
                "semantic_scholar",
                item.get("title") or "",
                url,
                (item.get("abstract") or "")[:400],
                request.query,
                "academic",
                evidence_role="primary",
                published_at=(str(item["year"]) if item.get("year") else None),
                author=authors[0] if authors else None,
                rank=rank,
                extra={
                    "authors": authors,
                    "doi": (item.get("externalIds") or {}).get("DOI"),
                },
            )
            if result:
                out.append(result)
        return out


validate_public_provider(SemanticScholarProvider.metadata)
