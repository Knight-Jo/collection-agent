"""Domain classification (port of source.ts)."""

from __future__ import annotations

import re
from typing import Literal
from urllib.parse import urlparse

from .models import SourceType

DomainKind = Literal[
    "government", "news", "encyclopedia", "social", "official", "other"
]

NEWS_DOMAINS = {
    "news.cn",
    "people.com.cn",
    "reuters.com",
    "bloomberg.com",
    "bbc.com",
    "thepaper.cn",
    "caixin.com",
    "chinanews.com",
}

# Forums, communities, stock bars, and republish aggregators: low-value
# reposts get a corpus-wide share cap instead of flooding the frontier
# (run 013: etbbs.com alone took 103/143 docs in run 011).
SOCIAL_DOMAINS = {
    "zhihu.com",
    "weibo.com",
    "reddit.com",
    "youtube.com",
    "etbbs.com",
    "xueqiu.com",
    "taoguba.com.cn",
    "guba.com.cn",
    "guba.eastmoney.com",
    "tieba.baidu.com",
}

# IR subdomains (ir.<company>) are first-party official sources.
_IR_HOST_RE = re.compile(r"^ir\.|\.ir\.", re.IGNORECASE)


def classify_domain(hostname_or_url: str) -> DomainKind:
    host = hostname_or_url
    if "://" in host:
        host = urlparse(host).hostname or host
    host = host.lower()
    if host.startswith("www."):
        host = host[4:]
    if host.endswith(".gov.cn") or host == "gov.cn" or host.endswith(".mil"):
        return "government"
    if re.fullmatch(r"(?:baike\.baidu\.com|[^.]+\.wikipedia\.org)", host):
        return "encyclopedia"
    if any(
        host == domain or host.endswith(f".{domain}")
        for domain in SOCIAL_DOMAINS
    ):
        return "social"
    if _IR_HOST_RE.search(host):
        return "official"
    if any(
        host == domain or host.endswith(f".{domain}")
        for domain in NEWS_DOMAINS
    ):
        return "news"
    return "other"


def domain_kind_label(kind: DomainKind) -> str:
    return {
        "government": "官方/政府",
        "news": "媒体",
        "encyclopedia": "百科",
        "social": "社交/自媒体",
        "official": "机构/企业官网",
        "other": "其他",
    }[kind]


def source_type_for_domain(hostname: str) -> SourceType:
    kind = classify_domain(hostname)
    if re.search(
        r"(?:\.edu(?:\.[a-z]{2})?|\.ac\.[a-z]{2})$", hostname.lower()
    ):
        return "academic"
    if kind in ("government", "news", "encyclopedia", "social", "official"):
        return kind
    return "other"
