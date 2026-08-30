"""Tavily search adapter (credentialed and opt-in)."""

from __future__ import annotations

from typing import Any

from ..provider import ProviderMetadata, SearchRequest
from .ai_native import CredentialedProvider, result


class TavilyProvider(CredentialedProvider):
    DEFAULT_BASE_URL = "https://api.tavily.com"
    metadata = ProviderMetadata(
        name="tavily",
        access_mode="OPEN_WEB_FALLBACK",
        requires_credentials=True,
        requires_payment=True,
        supports_anonymous=False,
    )

    async def search(self, client, request: SearchRequest):
        await self._admit()
        response = await client.post(
            f"{self.base_url}/search",
            json={
                "api_key": self.api_key,
                "query": request.query,
                "max_results": min(request.max_results, self.max_results),
                "include_answer": False,
            },
        )
        data: dict[str, Any] = await self._response_json(response)
        out = []
        for rank, item in enumerate(data.get("results", [])):
            if isinstance(item, dict):
                parsed = result("tavily", request, item, rank)
                if parsed:
                    out.append(parsed)
        return out
