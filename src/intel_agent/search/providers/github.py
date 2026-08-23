"""GitHub public search: repositories + issues, anonymous API.

Rate limits for anonymous requests are tight (10/min for search, 60/h core),
so the design goal is structured API first, SearXNG ``site:github.com``
fallback when rate-limited. No token, per the provider admission rule.
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
from .gitee import GiteeProvider

GITHUB_API = "https://api.github.com"
_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "intel-agent",
}


class GitHubProvider:
    metadata = ProviderMetadata(
        name="github",
        access_mode="OPEN_ANONYMOUS",
        supports_anonymous=True,
    )

    def __init__(
        self,
        *,
        base_url: str = GITHUB_API,
        searxng_url: str | None = None,
        gitee: GiteeProvider | None = None,
        min_interval: float = 6.0,
        max_results: int = 10,
    ) -> None:
        self.base_url = base_url
        self.searxng_url = searxng_url
        self.gitee = gitee
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
                "sort": "stars",
            },
            headers=_HEADERS,
        )
        res.raise_for_status()
        out: list[SearchResult] = []
        for rank, item in enumerate(res.json().get("items", [])):
            result = _provider_result(
                "github",
                item.get("full_name") or item.get("name", ""),
                item.get("html_url", ""),
                item.get("description") or "",
                request.query,
                "software",
                evidence_role=("secondary" if item.get("fork") else "primary"),
                published_at=item.get("pushed_at") or item.get("updated_at"),
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
        for rank, item in enumerate(res.json().get("items", [])):
            title = item.get("title") or ""
            if item.get("pull_request"):
                title = f"PR: {title}"
            result = _provider_result(
                "github",
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
                    "repo": item.get("repository_url", "").rsplit("/", 1)[-1],
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
        results = repos + issues
        if results:
            return results
        # Anonymous quota exhausted or API unreachable: degrade to the
        # China-accessible Gitee API, then to a site-scoped SearXNG query.
        if self.gitee is not None:
            gitee_results = await self.gitee.search(client, request)
            self.last_calls += self.gitee.last_calls
            if gitee_results:
                return gitee_results
        if not self.searxng_url:
            return []
        from .. import searxng_search

        await rate_limit("searxng", 0.5)
        self.last_calls += 1
        return await searxng_search(
            client,
            self.searxng_url,
            f"site:github.com {request.query}",
            min(request.max_results, self.max_results),
            {"language": request.language},
        )


REGISTRY.register(GitHubProvider())
