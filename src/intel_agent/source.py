"""Domain classification (port of source.ts)."""

from __future__ import annotations

import re
from typing import Literal
from urllib.parse import urlparse

from .models import SourceType

DomainKind = Literal["government", "news", "encyclopedia", "social", "official", "other"]

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
    if re.search(r"(^|\.)(zhihu|weibo|reddit|youtube)\.com$", host):
        return "social"
    if any(host == domain or host.endswith(f".{domain}") for domain in NEWS_DOMAINS):
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
    if re.search(r"(?:\.edu(?:\.[a-z]{2})?|\.ac\.[a-z]{2})$", hostname.lower()):
        return "academic"
    if kind in ("government", "news", "encyclopedia", "social"):
        return kind
    return "other"
