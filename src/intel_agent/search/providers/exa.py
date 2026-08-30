"""Exa search adapter (credentialed and opt-in)."""

from __future__ import annotations

from typing import Any

from ..provider import ProviderMetadata, SearchRequest
from .ai_native import CredentialedProvider, result


class ExaProvider(CredentialedProvider):
    DEFAULT_BASE_URL = "https://api.exa.ai"
    metadata = ProviderMetadata(
        name="exa",
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
        response = await client.post(
            f"{self.base_url}/search",
            headers={
                "x-api-key": self.api_key,
                "Content-Type": "application/json",
            },
            json={
                "query": request.query,
                "numResults": min(request.max_results, self.max_results),
                "contents": {"text": {"maxCharacters": 400}},
            },
        )
        data: dict[str, Any] = await self._response_json(response)
        out = []
        for rank, item in enumerate(data.get("results", [])):
            if isinstance(item, dict):
                parsed = result("exa", request, item, rank)
                if parsed:
                    out.append(parsed)
        return out
