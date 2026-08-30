"""Brave Web Search adapter (credentialed and opt-in)."""

from __future__ import annotations

from typing import Any

from ..provider import ProviderMetadata, SearchRequest
from .ai_native import CredentialedProvider, result


class BraveProvider(CredentialedProvider):
    DEFAULT_BASE_URL = "https://api.search.brave.com/res/v1"
    metadata = ProviderMetadata(
        name="brave",
        access_mode="OPEN_WEB_FALLBACK",
        requires_credentials=True,
        requires_payment=True,
        supports_anonymous=False,
    )

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        min_interval: float = 1.0,
        max_results: int = 10,
    ) -> None:
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            min_interval=min_interval,
            max_results=max_results,
        )

    async def search(self, client, request: SearchRequest):
        await self._admit()
        response = await client.get(
            f"{self.base_url}/web/search",
            params={
                "q": request.query,
                "count": min(request.max_results, self.max_results),
            },
            headers={
                "X-Subscription-Token": self.api_key,
                "Accept": "application/json",
            },
        )
        data: dict[str, Any] = await self._response_json(response)
        out = []
        for rank, item in enumerate(
            (data.get("web") or {}).get("results", [])
        ):
            if isinstance(item, dict):
                parsed = result("brave", request, item, rank)
                if parsed:
                    out.append(parsed)
        return out
