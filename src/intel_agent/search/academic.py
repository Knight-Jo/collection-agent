"""Academic search capability: arXiv + Crossref, S2 anonymous supplement.

Two-level routing: the LLM picks the *capability* (academic_search), this
module decides which providers run. arXiv + Crossref run concurrently; only
when the deduped effective result count is below ``supplement_threshold``
does the anonymous Semantic Scholar pool get queried as an enhancement
source. Every failure degrades instead of aborting.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from .provider import (
    SearchRequest,
    dedupe_results,
    load_search_cache,
    save_search_cache,
    search_cache_key,
)
from .providers.arxiv import ArxivProvider
from .providers.crossref import CrossrefProvider
from .providers.semantic_scholar import SemanticScholarProvider


async def academic_search(
    client: httpx.AsyncClient,
    query: str,
    *,
    arxiv: ArxivProvider | None,
    crossref: CrossrefProvider | None,
    semantic_scholar: SemanticScholarProvider | None,
    supplement_threshold: int = 3,
    time_range: str | None = None,
    language: str = "en",
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
            "provider": "academic",
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
            "engines_used": ["academic-cache"],
            "degraded": [],
        }
    degraded: list[str] = []
    arxiv_task = (
        asyncio.create_task(arxiv.search(client, request))
        if arxiv is not None
        else None
    )
    crossref_task = (
        asyncio.create_task(crossref.search(client, request))
        if crossref is not None
        else None
    )
    pending = [t for t in (arxiv_task, crossref_task) if t is not None]
    outcomes = (
        await asyncio.gather(*pending, return_exceptions=True)
        if pending
        else []
    )
    arxiv_results = outcomes[0] if arxiv_task is not None else None
    crossref_results = outcomes[1] if crossref_task is not None else None
    merged = _accept(arxiv_results, "arxiv", degraded)
    merged += _accept(crossref_results, "crossref", degraded)
    calls = (arxiv.last_calls if arxiv is not None else 0) + (
        crossref.last_calls if crossref is not None else 0
    )
    merged = dedupe_results(merged)
    if len(merged) < supplement_threshold and semantic_scholar is not None:
        supplement = await semantic_scholar.search(client, request)
        calls += semantic_scholar.last_calls
        if not supplement:
            degraded.append("semantic_scholar")
        merged = dedupe_results(merged + supplement)
    merged = merged[:max_results]
    save_search_cache(cache_dir, key, merged)
    return {
        "results": [r.model_dump() for r in merged],
        "provider_calls": calls,
        "engines_used": ["arxiv", "crossref"]
        + (["semantic_scholar"] if calls > 2 and not degraded else []),
        "degraded": degraded,
    }


def _accept(outcome: object, name: str, degraded: list[str]) -> list:
    if outcome is None:
        return []
    if isinstance(outcome, BaseException):
        degraded.append(name)
        return []
    return list(outcome)  # type: ignore[arg-type]
