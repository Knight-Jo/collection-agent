"""Multi-engine web search and query analysis (port of search.ts)."""

from __future__ import annotations

import asyncio
import re

import httpx
from pydantic import BaseModel

from . import search_queries as _search_queries
from .search_queries import (
    PUNCT_RE,
    STOP_TERMS,
    authoritative_variants,
)
from .source import DomainKind, classify_domain, domain_kind_label

GENERIC_TERMS = _search_queries.GENERIC_TERMS
STOP_WORDS = _search_queries.STOP_WORDS
build_query_variants = _search_queries.build_query_variants
extract_keywords = _search_queries.extract_keywords
industry_terms = _search_queries.industry_terms
is_broad_query = _search_queries.is_broad_query
is_semantic_duplicate = _search_queries.is_semantic_duplicate
query_similarity = _search_queries.query_similarity
tokenize_query = _search_queries.tokenize_query

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

SEARCH_TIMEOUT = 25.0


class SearchResult(BaseModel):
    engine: str
    title: str
    url: str
    snippet: str
    kind: DomainKind
    kind_label: str
    hits: int
    url_note: str | None = None


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
    s = s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    s = (
        s.replace("&quot;", '"')
        .replace("&#39;", "'")
        .replace("&apos;", "'")
        .replace("&nbsp;", " ")
    )

    def decode_num(m: re.Match) -> str:
        c = int(m.group(1))
        return chr(c) if 0 < c < 0x10FFFF else ""

    s = re.sub(r"&#(\d+);", decode_num, s)
    s = s.replace("\u200b", "").replace("\u200c", "").replace("\ufeff", "")
    return " ".join(s.split()).strip()


def _result(
    engine: str,
    title: str,
    url: str,
    snippet: str,
    query: str,
    url_note: str | None = None,
) -> SearchResult | None:
    title = title.strip()
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
    )


async def bing_search(
    client: httpx.AsyncClient, query: str, count: int
) -> list[SearchResult]:
    n = min(max(count, 1), 10)
    url = f"https://cn.bing.com/search?q={_q(query)}&setlang=en&count={n}"
    res = await client.get(
        url,
        headers={
            "User-Agent": UA,
            "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
        },
    )
    res.raise_for_status()
    html = res.text
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
    html = res.text
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
    html = res.text
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
    data = res.json()
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
) -> dict:
    """执行搜索：SearXNG → Bing → 百度 → 百度资讯，四路并发合并去重。"""
    opts = opts or {}
    close_client = client is None
    client = client or httpx.AsyncClient(timeout=SEARCH_TIMEOUT)
    try:
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

        engines: list[asyncio.Task[list[SearchResult]]] = []
        if searxng_url:
            engines.append(
                asyncio.create_task(
                    searxng_search(
                        client,
                        searxng_url,
                        query,
                        max_results,
                        {**opts, "language": language},
                    )
                )
            )
        engines += [
            asyncio.create_task(bing_search(client, query, max_results)),
            asyncio.create_task(baidu_search(client, query, max_results)),
            asyncio.create_task(baidu_news_search(client, query, max_results)),
        ]
        done = await asyncio.gather(*engines, return_exceptions=True)
        for result in done:
            if isinstance(result, BaseException):
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
                for v in authoritative_variants(query)[:2]
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
            return {
                "results": [r.model_dump() for r in results],
                "engineUsed": "+".join(engines_used) or "searxng",
            }
        return {
            "results": [],
            "engineUsed": "+".join(engines_used) or "none",
            "error": "四路引擎均无结果，换检索词或换语言重试。",
        }
    except Exception as e:
        return {
            "results": [],
            "engineUsed": "none",
            "error": f"搜索失败: {e}（网络受限时建议换用可访问站点复搜）",
        }
    finally:
        if close_client:
            await client.aclose()
