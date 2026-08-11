"""Multi-engine web search and query analysis (port of search.ts)."""

from __future__ import annotations

import asyncio
import re
from datetime import date

import httpx
from pydantic import BaseModel

from .source import DomainKind, classify_domain, domain_kind_label

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


PUNCT_RE = re.compile(r"[？?。.!！,，;；:：\"'“”‘’()（）]")
STOP_TERMS = {
    "如何", "怎样", "怎么", "什么", "为什么", "哪些", "多少", "进展", "情况", "现状", "未来", "最新",
    "官方", "公告", "争议", "质疑", "同比", "增长", "统计", "里程碑", "突破", "技术",
}
GENERIC_TERMS = {
    "投资", "融资", "商业化", "产业", "发展", "市场", "政策", "法规", "经济", "进展", "影响",
    "情况", "现状", "相关", "最新", "数据", "公告", "官方", "标准", "技术", "规模", "企业",
}
STOP_WORDS = STOP_TERMS | {
    "是否", "有没有", "是否已", "目前", "中国", "2026", "2025", "年",
    "和", "与", "及", "的", "了", "在", "对", "其", "the", "a", "an", "of", "for", "to", "in", "on",
}


def count_hits(query: str, title: str, snippet: str) -> int:
    terms = [
        t
        for t in (PUNCT_RE.sub(" ", query)).split()
        if len(t) >= 2 and t not in STOP_TERMS and not re.fullmatch(r"\d{4}", t)
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
    s = s.replace("&quot;", '"').replace("&#39;", "'").replace("&apos;", "'").replace("&nbsp;", " ")

    def decode_num(m: re.Match) -> str:
        c = int(m.group(1))
        return chr(c) if 0 < c < 0x10FFFF else ""

    s = re.sub(r"&#(\d+);", decode_num, s)
    s = s.replace("\u200b", "").replace("\u200c", "").replace("\ufeff", "")
    return " ".join(s.split()).strip()


def _result(engine: str, title: str, url: str, snippet: str, query: str, url_note: str | None = None) -> SearchResult | None:
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


async def bing_search(client: httpx.AsyncClient, query: str, count: int) -> list[SearchResult]:
    n = min(max(count, 1), 10)
    url = f"https://cn.bing.com/search?q={_q(query)}&setlang=en&count={n}"
    res = await client.get(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8"})
    res.raise_for_status()
    html = res.text
    out: list[SearchResult] = []
    for block in re.findall(r'<li class="b_algo"[\s\S]*?</li>', html)[:n]:
        am = re.search(r'<h2[^>]*><a[^>]*href="([^"]+)"[^>]*>([\s\S]*?)</a>', block)
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


async def baidu_search(client: httpx.AsyncClient, query: str, count: int) -> list[SearchResult]:
    n = min(max(count, 1), 10)
    url = f"https://www.baidu.com/s?wd={_q(query)}&rn={n}"
    res = await client.get(url, headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"})
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
        sm = re.search(r'class="[^"]*(?:c-abstract|content-right|_content_)[^"]*"[^>]*>([\s\S]*?)</(?:div|span)>', window) or re.search(
            r'class="[^"]*sc-paragraph[^"]*"[^>]*>([\s\S]*?)</p>', window
        )
        result = _result(
            "baidu",
            title,
            raw_url,
            sm.group(1) if sm else "",
            query,
            "百度跳转链接，web_fetch 直抓可能失败，建议以其标题为线索改用 Bing 复搜原文" if is_redirect else None,
        )
        if result:
            out.append(result)
    return out


async def baidu_news_search(client: httpx.AsyncClient, query: str, count: int) -> list[SearchResult]:
    n = min(max(count, 1), 10)
    url = f"https://www.baidu.com/s?tn=news&word={_q(query)}&rn={n}"
    res = await client.get(url, headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"})
    res.raise_for_status()
    html = res.text
    out: list[SearchResult] = []
    for block in re.findall(r"<h3[\s\S]*?</h3>", html)[:n]:
        am = re.search(r'<a[^>]*href="([^"]+)"[^>]*>([\s\S]*?)</a>', block)
        if not am:
            continue
        url, title = am.group(1), strip_tags(am.group(2))
        idx = html.find(block)
        sm = re.search(r'<span class="c-info"[^>]*>([\s\S]*?)</span>', html[idx : idx + 3000])
        result = _result("baidu-news", title, url, sm.group(1) if sm else "", query)
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
    res = await client.get(f"{searxng_url.rstrip('/')}/search", params=params, headers={"Accept": "application/json"})
    res.raise_for_status()
    data = res.json()
    out: list[SearchResult] = []
    for r in data.get("results", []):
        engine = re.sub(r"\s+", "", r.get("engines", ["searxng"])[0]) if r.get("engines") else "searxng"
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

        engines: list[asyncio.Task] = []
        if searxng_url:
            engines.append(asyncio.create_task(searxng_search(client, searxng_url, query, max_results, {**opts, "language": language})))
        engines += [
            asyncio.create_task(bing_search(client, query, max_results)),
            asyncio.create_task(baidu_search(client, query, max_results)),
            asyncio.create_task(baidu_news_search(client, query, max_results)),
        ]
        done = await asyncio.gather(*engines, return_exceptions=True)
        for result in done:
            if isinstance(result, Exception):
                continue
            collect(result)

        relevant_count = sum(
            1 for r in merged if r.hits >= 1 and r.kind in ("government", "news", "official")
        )
        if len(merged) == 0 or relevant_count < 2:
            variants = [re.sub(r"^site:\S+\s*", "", v, count=1) for v in authoritative_variants(query)[:2]]
            boosts = await asyncio.gather(
                *(searxng_search(client, searxng_url, v, max_results, {**opts, "language": language}) for v in variants),
                return_exceptions=True,
            ) if searxng_url and variants else []
            for result in boosts:
                if isinstance(result, Exception):
                    continue
                collect([r for r in result if r.kind in ("government", "official", "news")])

        kind_rank = {"government": 0, "news": 1, "official": 2, "encyclopedia": 3, "other": 4, "social": 5}
        merged.sort(key=lambda r: (kind_rank[r.kind], -r.hits))
        results = merged[:max_results]
        if results:
            return {"results": [r.model_dump() for r in results], "engineUsed": "+".join(engines_used) or "searxng"}
        return {"results": [], "engineUsed": "+".join(engines_used) or "none", "error": "四路引擎均无结果，换检索词或换语言重试。"}
    except Exception as e:
        return {"results": [], "engineUsed": "none", "error": f"搜索失败: {e}（网络受限时建议换用可访问站点复搜）"}
    finally:
        if close_client:
            await client.aclose()


# ---------------------------------------------------------------------------
# 检索词变体生成
# ---------------------------------------------------------------------------


def tokenize_query(query: str) -> list[str]:
    tokens: set[str] = set()
    for m in re.findall(r"[a-zA-Z][a-zA-Z0-9-]{1,}", query):
        w = m.lower()
        if w not in STOP_WORDS and len(w) >= 3:
            tokens.add(w)
    for seg in re.split(r"[^\u4e00-\u9fa5]+", query):
        if len(seg) >= 2 and seg not in STOP_WORDS and seg not in GENERIC_TERMS:
            tokens.add(seg)
    for m in re.findall(r"\d{4}", query):
        tokens.add(m)
    return list(tokens)


def is_broad_query(query: str) -> tuple[bool, str | None]:
    t = query.strip()
    if len(t) < 4:
        return True, "查询过短"
    tokens = [x for x in tokenize_query(t) if not re.fullmatch(r"\d{4}", x)]
    if len(tokens) < 2:
        return True, f"仅 {len(tokens)} 个实体词（如“{t}”），建议加限定词：年份/公司/机构/具体指标"
    return False, None


def query_similarity(a: str, b: str) -> float:
    A, B = tokenize_query(a), tokenize_query(b)
    if not A or not B:
        return 0.0
    inter = sum(1 for x in A if x in B)
    return inter / min(len(A), len(B))


def is_semantic_duplicate(a: str, b: str) -> bool:
    A = [x for x in tokenize_query(a) if x not in GENERIC_TERMS]
    B = [x for x in tokenize_query(b) if x not in GENERIC_TERMS]
    if len(A) < 3 or len(B) < 3:
        return False
    inter = sum(1 for x in A if x in B)
    return inter / min(len(A), len(B)) >= 0.6


def authoritative_variants(query: str) -> list[str]:
    kw = extract_keywords(query, 12)
    return [q for q in [
        f"site:gov.cn {kw}",
        f"site:ndrc.gov.cn {kw}",
        f"site:news.cn {kw}",
        f"site:people.com.cn {kw}",
    ] if len(q.split()) >= 2]


def industry_terms(question: str) -> list[str]:
    kw = extract_keywords(question, 12)
    extra: list[str] = []
    if re.search(r"投资|融资|商业化|市场|估值|商业", question):
        extra += [f"{kw} 融资 轮次 金额", f"{kw} 基金 投资 规模", f"{kw} IPO 上市 订单"]
    if re.search(r"政策|法规|条例|监管|标准", question):
        extra += [f"{kw} 条例 意见稿", f"{kw} 标准 体系"]
    if re.search(r"进展|发展|突破|技术", question):
        extra += [f"{kw} 里程碑 进展", f"{kw} 突破 技术"]
    return extra


def extract_keywords(question: str, max_len: int = 14) -> str:
    kw = re.sub(r"^(q\d*[:：\s]*|问题\d*[:：\s]*)", "", question, flags=re.I)
    terms = [
        t
        for t in re.sub(r"[？?。.!！,，;；:：\"'“”‘’()（）【】]", " ", kw).split()
        if len(t) >= 2 and t not in STOP_TERMS
    ]
    result = " ".join(terms)
    return result[:max_len] or question[:max_len]


def build_query_variants(topic: str, question: str) -> list[str]:
    kw = extract_keywords(question)
    year = date.today().year
    variants = [
        f"{topic} {kw}",
        f"{kw} {year}",
        f"{kw} 最新 数据",
        f"{kw} 官方 公告",
        f"{kw} 争议 质疑",
        f"{kw} 同比 增长 统计",
        f"EN:{kw} {year} official update（将关键词译为英文后搜索）",
    ]
    variants.extend(industry_terms(question))
    return [v for v in variants if len(v.split()) >= 2 or v.startswith("EN:")]
