"""360 News search: China-accessible news, server-rendered, real URLs.

Replaces the Sogou tier: news.sogou.com redirects anonymous requests to an
anti-spider wall (www.sogou.com/antispider/), while news.so.com serves
server-rendered results with direct article URLs (run 004 evidence).
"""

from __future__ import annotations

import re

from .. import UA, SearchResult, _provider_result, strip_tags
from ..provider import (
    REGISTRY,
    ProviderMetadata,
    SearchRequest,
    rate_limit,
)

_SO360_NEWS = "https://news.so.com/ns"


class So360NewsProvider:
    metadata = ProviderMetadata(
        name="so360_news",
        access_mode="OPEN_WEB_FALLBACK",
        supports_anonymous=True,
    )

    def __init__(
        self,
        *,
        base_url: str = _SO360_NEWS,
        min_interval: float = 2.0,
        max_results: int = 10,
    ) -> None:
        self.base_url = base_url
        self.min_interval = min_interval
        self.max_results = max_results
        self.last_calls = 0

    async def search(
        self, client, request: SearchRequest
    ) -> list[SearchResult]:
        await rate_limit(self.metadata.name, self.min_interval)
        self.last_calls = 1
        res = await client.get(
            self.base_url,
            params={"q": request.query},
            headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"},
        )
        res.raise_for_status()
        out: list[SearchResult] = []
        for block in re.findall(
            r'<li class="[^"]*res-list[^"]*"[^>]*data-url="([^"]+)"[^>]*>'
            r"([\s\S]*?)</li>",
            res.text,
        )[: min(request.max_results, self.max_results)]:
            url, body = block
            title_match = re.search(r"<h3[^>]*>([\s\S]*?)</h3>", body)
            title = strip_tags(title_match.group(1)) if title_match else ""
            snippet_match = re.search(
                r'<p class="summary[^"]*">([\s\S]*?)</p>', body
            )
            snippet = (
                strip_tags(snippet_match.group(1)) if snippet_match else ""
            )
            source_match = re.search(
                r'<cite class="sitename">([^<]*)</cite>', body
            )
            time_match = re.search(
                r'<span class="[^"]*time">([^<]*)</span>', body
            )
            result = _provider_result(
                "so360-news",
                title,
                url,
                snippet[:400],
                request.query,
                "news",
                published_at=time_match.group(1).strip()
                if time_match
                else None,
                rank=len(out),
                extra={
                    "source": (
                        source_match.group(1).strip() if source_match else None
                    )
                },
            )
            if result:
                out.append(result)
        return out


REGISTRY.register(So360NewsProvider())
