"""Search hit construction helpers shared by providers."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from ..contracts.research import (
    SearchHit,
    SearchOccurrence,
    SearchQuery,
    SourceType,
)
from .dedup import dedup_key


def query_id(query_text: str) -> str:
    return f"q-{hashlib.sha256(query_text.encode('utf-8')).hexdigest()[:16]}"


def make_hit(
    provider: str,
    query: SearchQuery,
    url: str,
    *,
    title: str | None,
    snippet: str | None,
    published_at: datetime | None,
    source_types: list[SourceType],
    rank: int | None,
    score: float | None,
    channel: str = "web",
    metadata: dict | None = None,
) -> SearchHit:
    key = dedup_key(url)
    occurrence = SearchOccurrence(
        provider=provider,
        query_id=query_id(query.text),
        provider_rank=rank,
        provider_score=score,
        observed_at=datetime.now(UTC),
        original_url=url,
        channel=channel,
        metadata=metadata or {},
    )
    return SearchHit(
        hit_id=f"hit-{hashlib.sha256(key.encode('utf-8')).hexdigest()[:16]}",
        url=url,
        dedup_key=key,
        title=title,
        snippet=snippet,
        published_at=published_at,
        source_types=source_types,
        occurrences=[occurrence],
    )
