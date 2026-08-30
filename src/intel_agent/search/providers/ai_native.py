"""Shared helpers for optional credentialed search providers."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from .. import MAX_SEARCH_RESPONSE_BYTES, SearchResult, _provider_result
from ..provider import ProviderMetadata, SearchRequest, rate_limit


class CredentialedProvider:
    """Small common base; instances are created only after key admission."""

    metadata: ProviderMetadata

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        min_interval: float,
        max_results: int,
    ) -> None:
        if not api_key.strip():
            raise ValueError("api_key must not be empty")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.min_interval = min_interval
        self.max_results = max_results
        self.last_calls = 0

    async def _response_json(self, response: httpx.Response) -> dict[str, Any]:
        response.raise_for_status()
        if len(response.content) > MAX_SEARCH_RESPONSE_BYTES:
            raise ValueError("search response exceeds configured limit")
        data = json.loads(
            response.content.decode(response.encoding or "utf-8")
        )
        if not isinstance(data, dict):
            raise ValueError("search response must be an object")
        return data

    async def _admit(self) -> None:
        await rate_limit(self.metadata.name, self.min_interval)
        self.last_calls = 1


def env_key(env_name: str) -> str | None:
    value = os.environ.get(env_name)
    return value.strip() if value and value.strip() else None


def result(
    provider: str,
    request: SearchRequest,
    item: dict[str, Any],
    rank: int,
    *,
    source_type: str = "other",
) -> SearchResult | None:
    url = str(item.get("url") or item.get("link") or "")
    title = str(item.get("title") or "")
    snippet = str(
        item.get("summary")
        or item.get("description")
        or item.get("snippet")
        or ""
    )
    return _provider_result(
        provider,
        title,
        url,
        snippet[:400],
        request.query,
        source_type,  # type: ignore[arg-type]
        published_at=item.get("publishedDate") or item.get("published_at"),
        author=item.get("author"),
        rank=rank,
        score=item.get("score"),
        extra={"raw_rank": rank},
    )
