"""GDELT DOC 2.0 Fulltext Search: keyless public news retrieval with dates."""

from __future__ import annotations

from .. import SearchResult, _provider_result
from ..provider import (
    ProviderMetadata,
    SearchRequest,
    rate_limit,
    validate_public_provider,
)

_GDELT_API = "https://api.gdeltproject.org/api/v2/doc/doc"
_TIMESPAN = {"day": "1D", "week": "1W", "month": "1M", "year": "1Y"}


class GDELTProvider:
    metadata = ProviderMetadata(
        name="gdelt",
        access_mode="OPEN_ANONYMOUS",
        supports_anonymous=True,
    )

    def __init__(
        self,
        *,
        base_url: str = _GDELT_API,
        min_interval: float = 1.0,
        max_results: int = 10,
    ) -> None:
        self.base_url = base_url
        self.min_interval = min_interval
        self.max_results = max_results
        self.last_calls = 0

    async def search(
        self, client, request: SearchRequest
    ) -> list[SearchResult]:
        params: dict = {
            "query": request.query,
            "mode": "artlist",
            "format": "json",
            "maxrecords": min(max(request.max_results * 3, 10), 75),
            "sort": "hybridrel",
        }
        if request.time_range in _TIMESPAN:
            params["timespan"] = _TIMESPAN[request.time_range]
        await rate_limit(self.metadata.name, self.min_interval)
        self.last_calls = 1
        res = await client.get(self.base_url, params=params)
        res.raise_for_status()
        articles = res.json().get("articles", [])
        out: list[SearchResult] = []
        for rank, item in enumerate(articles):
            result = _provider_result(
                "gdelt",
                item.get("title") or item.get("domain") or "",
                item.get("url", ""),
                "",  # artlist mode returns no snippets
                request.query,
                "news",
                published_at=item.get("seendate"),
                rank=rank,
                extra={
                    "domain": item.get("domain"),
                    "language": item.get("language"),
                    "image": item.get("socialimage"),
                },
            )
            if result:
                out.append(result)
        return out[: request.max_results]


validate_public_provider(GDELTProvider.metadata)
