"""News search capability: domestic tiers first, GDELT as optional last.

Cascade is sequential, not fan-out. Domestic-accessible tiers run first
(Baidu News, 360 News, SearXNG news); GDELT (global coverage with dates)
runs last and only when explicitly enabled - it is unreachable from
mainland-China networks, and defaulting it on makes every news_search pay
its timeout. Only when the deduped effective count is below
``supplement_threshold`` does the next tier run. A CJK query additionally
requires that enough effective results themselves look Chinese before the
cascade stops. Failures degrade; no credential required anywhere.
"""

from __future__ import annotations

import re
from pathlib import Path

import httpx

from . import SearchResult, baidu_news_search, searxng_search
from .provider import (
    SearchRequest,
    dedupe_results,
    load_search_cache,
    save_search_cache,
    search_cache_key,
)
from .providers.gdelt import GDELTProvider
from .providers.so360 import So360NewsProvider

_CJK_RE = re.compile(r"[\u4e00-\u9fa5]")


async def news_search(
    client: httpx.AsyncClient,
    query: str,
    *,
    gdelt: GDELTProvider | None,
    so360: So360NewsProvider | None,
    searxng_url: str | None,
    baidu: bool = True,
    supplement_threshold: int = 3,
    time_range: str | None = None,
    language: str = "zh-CN",
    max_results: int = 10,
    cache_dir: Path | None = None,
    cache_ttl: int = 3600,
) -> dict:
    request = SearchRequest(
        query=query,
        max_results=max_results,
        time_range=time_range,
        language=language,
    )
    key = search_cache_key(
        {
            "provider": "news",
            "query": query,
            "time_range": time_range,
            "filters": {"supplement_threshold": supplement_threshold},
            "max_results": max_results,
        }
    )
    cached = load_search_cache(cache_dir, key, cache_ttl)
    if cached is not None:
        return {
            "results": [r.model_dump() for r in cached],
            "provider_calls": 0,
            "engines_used": ["news-cache"],
            "degraded": [],
        }
    degraded: list[str] = []
    merged: list[SearchResult] = []
    calls = 0
    engines_used: list[str] = []
    is_cjk_query = bool(_CJK_RE.search(query))

    if baidu:
        engines_used.append("baidu-news")
        try:
            merged = dedupe_results(
                _as_news(await baidu_news_search(client, query, max_results))
            )
            calls += 1
        except Exception:
            degraded.append("baidu_news")

    if (
        not _sufficient(merged, supplement_threshold, is_cjk_query)
        and so360 is not None
    ):
        engines_used.append("so360-news")
        try:
            merged = dedupe_results(
                merged + await so360.search(client, request)
            )
            calls += so360.last_calls
        except Exception:
            degraded.append("so360_news")

    if (
        not _sufficient(merged, supplement_threshold, is_cjk_query)
        and searxng_url
    ):
        engines_used.append("searxng-news")
        try:
            merged = dedupe_results(
                merged
                + _as_news(
                    await searxng_search(
                        client,
                        searxng_url,
                        query,
                        max_results,
                        {
                            "category": "news",
                            "language": language,
                            "time_range": time_range,
                        }
                        if time_range
                        else {"category": "news", "language": language},
                    )
                )
            )
            calls += 1
        except Exception:
            degraded.append("searxng_news")

    if (
        not _sufficient(merged, supplement_threshold, is_cjk_query)
        and gdelt is not None
    ):
        engines_used.append("gdelt")
        try:
            merged = dedupe_results(
                merged + await gdelt.search(client, request)
            )
            calls += gdelt.last_calls
        except Exception:
            degraded.append("gdelt")

    merged = merged[:max_results]
    save_search_cache(cache_dir, key, merged)
    return {
        "results": [r.model_dump() for r in merged],
        "provider_calls": calls,
        "engines_used": engines_used,
        "degraded": degraded,
    }


def _as_news(results: list[SearchResult]) -> list[SearchResult]:
    """Tag degrade-tier results with the news source type so archived
    documents keep news attribution when GDELT is unreachable."""
    for result in results:
        if result.provider_source_type is None:
            result.provider_source_type = "news"
    return results


def _sufficient(
    merged: list[SearchResult], threshold: int, is_cjk_query: bool
) -> bool:
    if len(merged) < threshold:
        return False
    if is_cjk_query:
        cjk_results = sum(
            1
            for r in merged
            if _CJK_RE.search(r.title) or _CJK_RE.search(r.snippet)
        )
        return cjk_results >= threshold
    return True
