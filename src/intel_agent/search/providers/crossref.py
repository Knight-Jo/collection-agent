"""Crossref public REST pool: anonymous, no registration, polite pool limits."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from .. import SearchResult, _provider_result
from ..provider import (
    REGISTRY,
    ProviderMetadata,
    SearchRequest,
    rate_limit,
)

_CROSSREF_API = "https://api.crossref.org/works"


class CrossrefProvider:
    metadata = ProviderMetadata(
        name="crossref",
        access_mode="OPEN_ANONYMOUS",
        supports_anonymous=True,
    )

    def __init__(
        self,
        *,
        base_url: str = _CROSSREF_API,
        min_interval: float = 1.2,
        max_results: int = 10,
    ) -> None:
        self.base_url = base_url
        self.min_interval = min_interval
        self.max_results = max_results
        self.last_calls = 0

    async def search(
        self, client, request: SearchRequest
    ) -> list[SearchResult]:
        params: dict = {
            "query": request.query,
            "rows": min(request.max_results, self.max_results),
            "select": (
                "DOI,title,author,URL,published,container-title,"
                "is-referenced-by-count"
            ),
        }
        if request.time_range:
            start, end = _crossref_date_range(request.time_range)
            if start and end:
                params["filter"] = (
                    f"from-pub-date:{start},until-pub-date:{end}"
                )
        await rate_limit(self.metadata.name, self.min_interval)
        self.last_calls = 1
        res = await client.get(
            self.base_url,
            params=params,
            headers={"User-Agent": "intel-agent (anonymous public pool)"},
        )
        res.raise_for_status()
        items = res.json().get("message", {}).get("items", [])
        out: list[SearchResult] = []
        for rank, item in enumerate(items):
            title = (item.get("title") or [""])[0]
            url = item.get("URL") or ""
            if not url and item.get("DOI"):
                url = f"https://doi.org/{item['DOI']}"
            authors = [
                f"{a.get('given', '')} {a.get('family', '')}".strip()
                for a in item.get("author", [])
            ]
            result = _provider_result(
                "crossref",
                title,
                url,
                "",  # publisher pages are fetched for the abstract
                request.query,
                "academic",
                evidence_role="primary",
                published_at=_date_from_parts(item.get("published")),
                author=authors[0] if authors else None,
                rank=rank,
                extra={
                    "doi": item.get("DOI"),
                    "journal": (item.get("container-title") or [""])[0],
                    "citation_count": item.get("is-referenced-by-count"),
                    "authors": authors,
                },
            )
            if result:
                out.append(result)
        return out


def _date_from_parts(published: dict | None) -> str | None:
    if not published or not published.get("date-parts"):
        return None
    parts = published["date-parts"][0]
    if not parts or not parts[0]:
        return None
    value = str(parts[0])
    if len(parts) >= 2 and parts[1]:
        value += f"-{int(parts[1]):02d}"
    if len(parts) >= 3 and parts[2]:
        value += f"-{int(parts[2]):02d}"
    return value


def _crossref_date_range(time_range: str) -> tuple[str | None, str | None]:
    days = {"day": 1, "week": 7, "month": 30, "year": 365}.get(time_range)
    if days is None:
        return None, None
    end = datetime.now(UTC).date()
    start = end - timedelta(days=days)
    return start.isoformat(), end.isoformat()


REGISTRY.register(CrossrefProvider())
