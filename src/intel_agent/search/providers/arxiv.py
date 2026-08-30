"""arXiv export API: anonymous, no key, polite 1 request / 3 seconds."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from .. import SearchResult, _provider_result
from ..provider import (
    ProviderMetadata,
    SearchRequest,
    rate_limit,
    validate_public_provider,
)

_ARXIV_API = "https://export.arxiv.org/api/query"
_ATOM = "{http://www.w3.org/2005/Atom}"


class ArxivProvider:
    metadata = ProviderMetadata(
        name="arxiv",
        access_mode="OPEN_ANONYMOUS",
        supports_anonymous=True,
    )

    def __init__(
        self,
        *,
        base_url: str = _ARXIV_API,
        min_interval: float = 3.0,
        max_results: int = 10,
    ) -> None:
        self.base_url = base_url
        self.min_interval = min_interval
        self.max_results = max_results
        self.last_calls = 0

    async def search(
        self, client, request: SearchRequest
    ) -> list[SearchResult]:
        query = request.query
        if request.time_range:
            start, end = _arxiv_date_range(request.time_range)
            if start and end:
                query = f"{query} AND submittedDate:[{start} TO {end}]"
        await rate_limit(self.metadata.name, self.min_interval)
        self.last_calls = 1
        res = await client.get(
            self.base_url,
            params={
                "search_query": f"all:{query}",
                "start": 0,
                "max_results": min(request.max_results, self.max_results),
                "sortBy": "submittedDate",
                "sortOrder": "descending",
            },
        )
        res.raise_for_status()
        root = ET.fromstring(res.text)
        out: list[SearchResult] = []
        for rank, entry in enumerate(root.findall(f"{_ATOM}entry")):
            authors = [
                (node.findtext(f"{_ATOM}name") or "")
                for node in entry.findall(f"{_ATOM}author")
            ]
            published = entry.findtext(f"{_ATOM}published")
            result = _provider_result(
                "arxiv",
                (entry.findtext(f"{_ATOM}title") or "").strip(),
                (entry.findtext(f"{_ATOM}id") or "").strip(),
                (entry.findtext(f"{_ATOM}summary") or "").strip()[:400],
                request.query,
                "academic",
                evidence_role="primary",
                published_at=published[:10] if published else None,
                author=authors[0] if authors else None,
                rank=rank,
                extra={
                    "authors": authors,
                    "updated": entry.findtext(f"{_ATOM}updated"),
                },
            )
            if result:
                out.append(result)
        return out


def _arxiv_date_range(time_range: str) -> tuple[str | None, str | None]:
    from datetime import UTC, datetime, timedelta

    days = {"day": 1, "week": 7, "month": 30, "year": 365}.get(time_range)
    if days is None:
        return None, None
    end = datetime.now(UTC).date()
    start = end - timedelta(days=days)
    return start.isoformat(), end.isoformat()


validate_public_provider(ArxivProvider.metadata)
