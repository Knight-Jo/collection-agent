"""Provider infrastructure: admission-controlled registry over typed results.

Every vertical search source goes through this module. Providers declare
static metadata (access mode, credential/payment requirements); the registry
enforces the admission rule at registration time so a paid or
credential-requiring provider can never silently ship into the production
stack. The runtime acceptance test ``test_search_stack_without_credentials``
re-checks the same invariants over the fully registered set.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field

from . import SearchResult

AccessMode = str

ALLOWED_ACCESS_MODES = {
    "OPEN_ANONYMOUS",
    "OPEN_SELF_HOSTED",
    "OPEN_WEB_FALLBACK",
}


class ProviderMetadata(BaseModel):
    name: str
    access_mode: AccessMode
    requires_credentials: bool = False
    requires_payment: bool = False
    supports_anonymous: bool = True


class SearchRequest(BaseModel):
    query: str
    max_results: int = Field(default=10, ge=1, le=50)
    time_range: str | None = None
    language: str = "zh-CN"
    filters: dict = Field(default_factory=dict)


class SearchProvider(Protocol):
    metadata: ProviderMetadata

    async def search(
        self, client, request: SearchRequest
    ) -> list[SearchResult]: ...


def validate_public_provider(metadata: ProviderMetadata) -> None:
    """Reject providers that violate the anonymous production policy."""
    if metadata.requires_payment:
        raise ValueError(
            f"provider {metadata.name}: requires_payment is not allowed "
            "in the production search stack"
        )
    if metadata.requires_credentials:
        raise ValueError(
            f"provider {metadata.name}: requires_credentials is not "
            "allowed in the production search stack"
        )
    if metadata.access_mode not in ALLOWED_ACCESS_MODES:
        raise ValueError(
            f"provider {metadata.name}: access_mode "
            f"{metadata.access_mode!r} not in {sorted(ALLOWED_ACCESS_MODES)}"
        )
    if not metadata.supports_anonymous:
        raise ValueError(
            f"provider {metadata.name}: anonymous access required"
        )


# name -> (min_interval_seconds, asyncio.Lock, last_call_monotonic)
_rate_state: dict[str, tuple[float, asyncio.Lock, float]] = {}


def _rate_slot(name: str, min_interval: float) -> tuple[asyncio.Lock, float]:
    entry = _rate_state.get(name)
    if entry is None:
        entry = (min_interval, asyncio.Lock(), 0.0)
        _rate_state[name] = entry
    return entry[1], entry[2]


async def rate_limit(name: str, min_interval: float) -> None:
    """Sleep so successive calls to one provider respect its polite interval."""
    if min_interval <= 0:
        return
    lock, last = _rate_slot(name, min_interval)
    async with lock:
        now = time.monotonic()
        wait = last + min_interval - now
        if wait > 0:
            await asyncio.sleep(wait)
        _rate_state[name] = (min_interval, lock, time.monotonic())


def search_cache_key(params: dict) -> str:
    """Content hash over provider + query + retrieval params, never the query alone."""
    return hashlib.sha256(
        json.dumps(params, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def load_search_cache(
    cache_dir: Path | None, key: str, ttl_seconds: int
) -> list[SearchResult] | None:
    if not cache_dir or ttl_seconds <= 0:
        return None
    path = cache_dir / "search" / f"{key}.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if time.time() - payload["fetched_at"] > ttl_seconds:
            return None
        return [
            SearchResult.model_validate(item) for item in payload["results"]
        ]
    except (OSError, ValueError, KeyError):
        return None


def save_search_cache(
    cache_dir: Path | None, key: str, results: list[SearchResult]
) -> None:
    if not cache_dir:
        return
    path = cache_dir / "search" / f"{key}.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "fetched_at": time.time(),
                    "results": [r.model_dump() for r in results],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except OSError:
        return


def normalize_result_url(url: str) -> str:
    """Dedupe key: drop www prefix and fragments, as web_search does."""
    key = re.sub(r"^https?://www\.", "https://", url)
    return re.sub(r"#.*$", "", key)


def dedupe_results(results: list[SearchResult]) -> list[SearchResult]:
    seen: set[str] = set()
    out: list[SearchResult] = []
    for result in results:
        key = normalize_result_url(result.url)
        if key in seen:
            continue
        seen.add(key)
        out.append(result)
    return out


def credentialed_providers(config) -> list[SearchProvider]:
    """Build only explicitly enabled providers with present environment keys."""
    from .providers.brave import BraveProvider
    from .providers.exa import ExaProvider
    from .providers.tavily import TavilyProvider

    providers: list[SearchProvider] = []
    for name, cls in (
        ("exa", ExaProvider),
        ("brave", BraveProvider),
        ("tavily", TavilyProvider),
    ):
        cfg = getattr(config, name)
        key = os.environ.get(cfg.api_key_env, "").strip()
        if not cfg.enabled or not key:
            continue
        providers.append(
            cls(
                api_key=key,
                base_url=cfg.base_url or cls.DEFAULT_BASE_URL,
                min_interval=cfg.rate_limit,
                max_results=cfg.max_results,
            )
        )
    return providers
