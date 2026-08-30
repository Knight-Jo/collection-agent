"""SearXNG adapter: wraps the existing engine with provider metadata."""

from __future__ import annotations

from .. import SearchResult, searxng_search
from ..provider import (
    ProviderMetadata,
    SearchRequest,
    rate_limit,
    validate_public_provider,
)


class SearXNGProvider:
    metadata = ProviderMetadata(
        name="searxng",
        access_mode="OPEN_SELF_HOSTED",
        supports_anonymous=True,
    )

    def __init__(
        self,
        base_url: str,
        *,
        min_interval: float = 0.5,
        max_results: int = 10,
    ) -> None:
        self.base_url = base_url
        self.min_interval = min_interval
        self.max_results = max_results
        self.last_calls = 0
        self.last_unresponsive: list[str] = []

    async def search(
        self, client, request: SearchRequest
    ) -> list[SearchResult]:
        unresponsive: list[str] = []
        await rate_limit(self.metadata.name, self.min_interval)
        self.last_calls = 1
        results = await searxng_search(
            client,
            self.base_url,
            request.query,
            min(request.max_results, self.max_results),
            {
                "language": request.language,
                "time_range": request.time_range,
            }
            if request.time_range
            else {"language": request.language},
            unresponsive=unresponsive,
        )
        self.last_unresponsive = unresponsive
        return results


validate_public_provider(SearXNGProvider.metadata)
