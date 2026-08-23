"""Gitee public search: China-accessible Git host, anonymous v5 API.

Domestic degrade tier for the github capability: no token, plain JSON
arrays (unlike GitHub's ``{items: []}`` envelope).
"""

from __future__ import annotations

import asyncio

from .. import SearchResult, _provider_result
from ..provider import (
    REGISTRY,
    ProviderMetadata,
    SearchRequest,
    rate_limit,
)

_GITEE_API = "https://gitee.com/api/v5"
_HEADERS = {"User-Agent": "intel-agent"}


class GiteeProvider:
    metadata = ProviderMetadata(
        name="gitee",
        access_mode="OPEN_ANONYMOUS",
        supports_anonymous=True,
    )

    def __init__(
        self,
        *,
        base_url: str = _GITEE_API,
        min_interval: float = 1.0,
        max_results: int = 10,
    ) -> None:
        self.base_url = base_url
        self.min_interval = min_interval
        self.max_results = max_results
        self.last_calls = 0

    async def _repos(
        self, client, request: SearchRequest
    ) -> list[SearchResult]:
        res = await client.get(
            f"{self.base_url}/search/repositories",
            params={
                "q": request.query,
                "per_page": min(request.max_results, self.max_results),
                "sort": "stars_count",
            },
            headers=_HEADERS,
        )
        res.raise_for_status()
        out: list[SearchResult] = []
        for rank, item in enumerate(res.json()):
            result = _provider_result(
                "gitee",
                item.get("full_name") or item.get("name", ""),
                item.get("html_url", ""),
                item.get("description") or "",
                request.query,
                "software",
                evidence_role=("secondary" if item.get("fork") else "primary"),
                published_at=item.get("updated_at"),
                author=(item.get("owner") or {}).get("login"),
                rank=rank,
                score=item.get("stargazers_count"),
                extra={
                    "kind": "repository",
                    "stars": item.get("stargazers_count"),
                    "forks": item.get("forks_count"),
                    "language": item.get("language"),
                    "fork": item.get("fork"),
                    "repo": item.get("full_name"),
                    "updated_at": item.get("updated_at"),
                },
            )
            if result:
                out.append(result)
        return out

    async def _issues(
        self, client, request: SearchRequest
    ) -> list[SearchResult]:
        res = await client.get(
            f"{self.base_url}/search/issues",
            params={
                "q": request.query,
                "per_page": min(request.max_results, self.max_results),
            },
            headers=_HEADERS,
        )
        res.raise_for_status()
        out: list[SearchResult] = []
        for rank, item in enumerate(res.json()):
            title = item.get("title") or ""
            if item.get("pull_request"):
                title = f"PR: {title}"
            result = _provider_result(
                "gitee",
                title,
                item.get("html_url", ""),
                (item.get("body") or "")[:400],
                request.query,
                "software",
                evidence_role="supporting",
                published_at=item.get("created_at"),
                author=(item.get("user") or {}).get("login"),
                rank=rank,
                extra={
                    "kind": "pull_request"
                    if item.get("pull_request")
                    else "issue",
                    "issue_number": item.get("number"),
                    "state": item.get("state"),
                    "repo": (item.get("repository") or {}).get("full_name"),
                },
            )
            if result:
                out.append(result)
        return out

    async def search(
        self, client, request: SearchRequest
    ) -> list[SearchResult]:
        await rate_limit(self.metadata.name, self.min_interval)
        self.last_calls = 2
        repos, issues = await asyncio.gather(
            self._repos(client, request),
            self._issues(client, request),
            return_exceptions=True,
        )
        if isinstance(repos, BaseException):
            repos = []
        if isinstance(issues, BaseException):
            issues = []
        return repos + issues


REGISTRY.register(GiteeProvider())
