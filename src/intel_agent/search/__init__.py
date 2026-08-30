"""Multi-engine web search and query analysis (port of search.ts)."""

from __future__ import annotations

import asyncio
import html
import json
import re

import httpx
from pydantic import BaseModel, Field

from ..models import EvidenceRole, IntelError, SourceType, utc_now
from ..search_queries import (
    PUNCT_RE,
    STOP_TERMS,
    authoritative_variants,
)
from ..source import DomainKind, classify_domain, domain_kind_label

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

SEARCH_TIMEOUT = 25.0
MAX_SEARCH_RESPONSE_BYTES = 2_000_000


class SearchResult(BaseModel):
    # Legacy general-search fields; kept until every consumer migrates.
    engine: str
    kind: DomainKind
    kind_label: str
    hits: int
    url_note: str | None = None
    # Shared fields.
    title: str
    url: str
    snippet: str
    fetchable: bool = True
    # Vertical-provider fields (additive, see plan: only add, never remove).
    provider: str = ""
    provider_source_type: SourceType | None = None
    evidence_role: EvidenceRole | None = None
    published_at: str | None = None
    author: str | None = None
    rank: int | None = None
    score: float | None = None
    discovered_at: str = Field(default_factory=utc_now)
    extra: dict = Field(default_factory=dict)


def count_hits(query: str, title: str, snippet: str) -> int:
    terms = [
        t
        for t in (PUNCT_RE.sub(" ", query)).split()
        if len(t) >= 2
        and t not in STOP_TERMS
        and not re.fullmatch(r"\d{4}", t)
    ]
    if not terms:
        return 0
    hits = 0
    for t in terms:
        if t in title:
            hits += 2
        elif t in snippet:
            hits += 1
    return hits


def strip_tags(s: str) -> str:
    s = re.sub(r"<script[\s\S]*?</script>", " ", s, flags=re.I)
    s = re.sub(r"<style[\s\S]*?</style>", " ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s).replace("\xa0", " ")
    s = s.replace("\u200b", "").replace("\u200c", "").replace("\ufeff", "")
    return " ".join(s.split()).strip()


def _response_text(response: httpx.Response) -> str:
    body = response.content
    if len(body) > MAX_SEARCH_RESPONSE_BYTES:
        raise IntelError(
            "RESPONSE_TOO_LARGE",
            f"搜索响应超过 {MAX_SEARCH_RESPONSE_BYTES} 字节",
            downloaded_bytes=len(body),
        )
    encoding = response.encoding or "utf-8"
    return body.decode(encoding, errors="replace")


def _result(
    engine: str,
    title: str,
    url: str,
    snippet: str,
    query: str,
    url_note: str | None = None,
    fetchable: bool = True,
) -> SearchResult | None:
    title = title.strip()
    url = html.unescape(url).strip()
    if not title or not re.match(r"^https?://", url):
        return None
    kind = classify_domain(url)
    return SearchResult(
        engine=engine,
        title=title,
        url=url,
        snippet=snippet.strip(),
        kind=kind,
        kind_label=domain_kind_label(kind),
        hits=count_hits(query, title, snippet),
        url_note=url_note,
        fetchable=fetchable,
    )


def _provider_result(
    provider: str,
    title: str,
    url: str,
    snippet: str,
    query: str,
    source_type: SourceType,
    *,
    evidence_role: EvidenceRole | None = None,
    published_at: str | None = None,
    author: str | None = None,
    rank: int | None = None,
    score: float | None = None,
    fetchable: bool = True,
    extra: dict | None = None,
) -> SearchResult | None:
    """Build a vertical-provider result; provider source type wins over domain.

    ``kind``/``hits`` are still populated from domain classification so the
    general ranking path keeps working when vertical results are merged in.
    """
    title = title.strip()
    url = html.unescape(url).strip()
    if not title or not re.match(r"^https?://", url):
        return None
    kind = classify_domain(url)
    return SearchResult(
        engine=provider,
        provider=provider,
        title=title,
        url=url,
        snippet=snippet.strip(),
        kind=kind,
        kind_label=domain_kind_label(kind),
        hits=count_hits(query, title, snippet),
        provider_source_type=source_type,
        evidence_role=evidence_role,
        published_at=published_at,
        author=author,
        rank=rank,
        score=score,
        fetchable=fetchable,
        extra=extra or {},
    )


async def bing_search(
    client: httpx.AsyncClient, query: str, count: int
) -> list[SearchResult]:
    n = min(max(count, 1), 10)
    language = "zh-CN" if re.search(r"[\u4e00-\u9fa5]", query) else "en-US"
    url = (
        f"https://www.bing.com/search?q={_q(query)}"
        f"&setlang={language}&count={n}"
    )
    res = await client.get(
        url,
        headers={
            "User-Agent": UA,
            "Accept-Language": (
                "zh-CN,zh;q=0.9,en;q=0.8"
                if language == "zh-CN"
                else "en-US,en;q=0.9"
            ),
        },
    )
    res.raise_for_status()
    html = _response_text(res)
    out: list[SearchResult] = []
    for block in re.findall(r'<li class="b_algo"[\s\S]*?</li>', html)[:n]:
        am = re.search(
            r'<h2[^>]*><a[^>]*href="([^"]+)"[^>]*>([\s\S]*?)</a>', block
        )
        if not am:
            continue
        url, title = am.group(1), strip_tags(am.group(2))
        pm = re.search(r"<p[^>]*>([\s\S]*?)</p>", block)
        result = _result("bing", title, url, pm.group(1) if pm else "", query)
        if result:
            out.append(result)
    return out


def _q(query: str) -> str:
    from urllib.parse import quote

    return quote(query)


async def baidu_search(
    client: httpx.AsyncClient, query: str, count: int
) -> list[SearchResult]:
    n = min(max(count, 1), 10)
    url = f"https://www.baidu.com/s?wd={_q(query)}&rn={n}"
    res = await client.get(
        url, headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"}
    )
    res.raise_for_status()
    html = _response_text(res)
    out: list[SearchResult] = []
    for block in re.findall(r"<h3[\s\S]*?</h3>", html)[:n]:
        am = re.search(r'<a[^>]*href="([^"]+)"[^>]*>([\s\S]*?)</a>', block)
        if not am:
            continue
        raw_url, title = am.group(1), strip_tags(am.group(2))
        if not title:
            continue
        is_redirect = "baidu.com/link" in raw_url
        idx = html.find(block)
        window = html[idx : idx + 4000]
        sm = re.search(
            r'class="[^"]*(?:c-abstract|content-right|_content_)[^"]*"[^>]*>([\s\S]*?)</(?:div|span)>',
            window,
        ) or re.search(
            r'class="[^"]*sc-paragraph[^"]*"[^>]*>([\s\S]*?)</p>', window
        )
        result = _result(
            "baidu",
            title,
            raw_url,
            sm.group(1) if sm else "",
            query,
            "百度跳转链接，web_fetch 直抓可能失败，建议以其标题为线索改用 Bing 复搜原文"
            if is_redirect
            else None,
            not is_redirect,
        )
        if result:
            out.append(result)
    return out


async def baidu_news_search(
    client: httpx.AsyncClient, query: str, count: int
) -> list[SearchResult]:
    n = min(max(count, 1), 10)
    url = f"https://www.baidu.com/s?tn=news&word={_q(query)}&rn={n}"
    res = await client.get(
        url, headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"}
    )
    res.raise_for_status()
    html = _response_text(res)
    out: list[SearchResult] = []
    for block in re.findall(r"<h3[\s\S]*?</h3>", html)[:n]:
        am = re.search(r'<a[^>]*href="([^"]+)"[^>]*>([\s\S]*?)</a>', block)
        if not am:
            continue
        url, title = am.group(1), strip_tags(am.group(2))
        idx = html.find(block)
        sm = re.search(
            r'<span class="c-info"[^>]*>([\s\S]*?)</span>',
            html[idx : idx + 3000],
        )
        result = _result(
            "baidu-news", title, url, sm.group(1) if sm else "", query
        )
        if result:
            out.append(result)
    return out


async def searxng_search(
    client: httpx.AsyncClient,
    searxng_url: str,
    query: str,
    count: int,
    opts: dict | None = None,
    unresponsive: list[str] | None = None,
) -> list[SearchResult]:
    opts = opts or {}
    params = {
        "q": query,
        "format": "json",
        "language": opts.get("language", "zh-CN"),
        "categories": opts.get("category", "general"),
        "safesearch": "0",
    }
    if opts.get("time_range"):
        params["time_range"] = opts["time_range"]
    res = await client.get(
        f"{searxng_url.rstrip('/')}/search",
        params=params,
        headers={"Accept": "application/json"},
    )
    res.raise_for_status()
    data = json.loads(_response_text(res))
    if unresponsive is not None:
        for engine in data.get("unresponsive_engines", []):
            unresponsive.append(str(engine[0]))
    out: list[SearchResult] = []
    for r in data.get("results", []):
        engine = (
            re.sub(r"\s+", "", r.get("engines", ["searxng"])[0])
            if r.get("engines")
            else "searxng"
        )
        result = _result(
            f"searxng:{engine}",
            r.get("title", ""),
            r.get("url", ""),
            (r.get("content", "") or "")[:400],
            query,
        )
        if result:
            out.append(result)
            if len(out) >= count:
                break
    return out


async def web_search(
    query: str,
    max_results: int = 5,
    client: httpx.AsyncClient | None = None,
    searxng_url: str | None = "http://127.0.0.1:8888",
    opts: dict | None = None,
    ai_native_providers: list | None = None,
) -> dict:
    """Search SearXNG, Bing, Baidu and Baidu News concurrently, merging deduped results."""
    opts = opts or {}
    close_client = client is None
    client = client or httpx.AsyncClient(timeout=SEARCH_TIMEOUT)
    try:
        from .provider import SearchRequest

        has_zh = re.search(r"[\u4e00-\u9fa5]", query) is not None
        language = opts.get("language") or ("zh-CN" if has_zh else "en")
        merged: list[SearchResult] = []
        seen: set[str] = set()
        engines_used: list[str] = []

        def collect(results: list[SearchResult]) -> None:
            for r in results:
                key = re.sub(r"^https?://www\.", "https://", r.url)
                key = re.sub(r"#.*$", "", key)
                if key in seen:
                    continue
                seen.add(key)
                merged.append(r)
            if results and results[0].engine not in engines_used:
                engines_used.append(results[0].engine)

        engines: list[tuple[str, asyncio.Task[list[SearchResult]]]] = []
        if searxng_url:
            engines.append(
                (
                    "searxng",
                    asyncio.create_task(
                        searxng_search(
                            client,
                            searxng_url,
                            query,
                            max_results,
                            {**opts, "language": language},
                        )
                    ),
                )
            )
        engines += [
            (
                "bing",
                asyncio.create_task(bing_search(client, query, max_results)),
            ),
            (
                "baidu",
                asyncio.create_task(baidu_search(client, query, max_results)),
            ),
            (
                "baidu-news",
                asyncio.create_task(
                    baidu_news_search(client, query, max_results)
                ),
            ),
        ]
        for provider in ai_native_providers or []:
            engines.append(
                (
                    provider.metadata.name,
                    asyncio.create_task(
                        provider.search(
                            client,
                            SearchRequest(
                                query=query,
                                max_results=max_results,
                                language=language,
                                time_range=opts.get("time_range"),
                            ),
                        ),
                    ),
                )
            )
        done = await asyncio.gather(
            *(task for _, task in engines), return_exceptions=True
        )
        degraded: list[str] = []
        for (name, _), result in zip(engines, done, strict=True):
            if isinstance(result, BaseException):
                degraded.append(name)
                continue
            collect(result)

        relevant_count = sum(
            1
            for r in merged
            if r.hits >= 1 and r.kind in ("government", "news", "official")
        )
        if len(merged) == 0 or relevant_count < 2:
            variants = [
                re.sub(r"^site:\S+\s*", "", v, count=1)
                for v in authoritative_variants(query)
            ]
            boosts = (
                await asyncio.gather(
                    *(
                        searxng_search(
                            client,
                            searxng_url,
                            v,
                            max_results,
                            {**opts, "language": language},
                        )
                        for v in variants
                    ),
                    return_exceptions=True,
                )
                if searxng_url and variants
                else []
            )
            for result in boosts:
                if isinstance(result, BaseException):
                    continue
                collect(
                    [
                        r
                        for r in result
                        if r.kind in ("government", "official", "news")
                    ]
                )

        kind_rank = {
            "government": 0,
            "news": 1,
            "official": 2,
            "encyclopedia": 3,
            "other": 4,
            "social": 5,
        }
        merged.sort(key=lambda r: (kind_rank[r.kind], -r.hits))
        results = merged[:max_results]
        if results:
            response = {
                "results": [r.model_dump() for r in results],
                "engineUsed": "+".join(engines_used) or "searxng",
            }
            if degraded:
                response["degraded"] = degraded
            return response
        response = {
            "results": [],
            "engineUsed": "+".join(engines_used) or "none",
            "error": "四路引擎均无结果，换检索词或换语言重试。",
        }
        if degraded:
            response["degraded"] = degraded
        return response
    except Exception as e:
        return {
            "results": [],
            "engineUsed": "none",
            "error": f"搜索失败: {e}（网络受限时建议换用可访问站点复搜）",
        }
    finally:
        if close_client:
            await client.aclose()
