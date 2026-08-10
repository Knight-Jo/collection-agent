"""URL security: private address blocking, DNS pinning (port of security.ts)."""

from __future__ import annotations

import ipaddress
import socket
from typing import Awaitable, Callable
from urllib.parse import urlparse

import tldextract

from .models import IntelError

AddressResolver = Callable[[str], Awaitable[list[str]]]

BLOCKED_NETWORKS = [
    ipaddress.ip_network(net)
    for net in [
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.0.0.0/24",
        "192.0.2.0/24",
        "192.168.0.0/16",
        "198.18.0.0/15",
        "198.51.100.0/24",
        "203.0.113.0/24",
        "224.0.0.0/4",
        "240.0.0.0/4",
        "::/128",
        "::1/128",
        "fc00::/7",
        "fe80::/10",
        "ff00::/8",
        "2001:db8::/32",
    ]
]


def strip_ipv6_brackets(hostname: str) -> str:
    return hostname[1:-1] if hostname.startswith("[") and hostname.endswith("]") else hostname


def is_public_address(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(strip_ipv6_brackets(address))
    except ValueError:
        return False
    return not any(ip in net for net in BLOCKED_NETWORKS)


async def default_resolver(hostname: str) -> list[str]:
    try:
        return sorted({entry[4][0] for entry in socket.getaddrinfo(hostname, None)})
    except socket.gaierror:
        return []


async def resolve_public_url(raw: str, resolver: AddressResolver | None = None) -> tuple[object, list[str]]:
    resolver = resolver or default_resolver
    try:
        from urllib.parse import urlsplit

        parsed = urlsplit(raw)
    except Exception:
        raise IntelError("UNSAFE_URL", f"无效 URL: {raw}")
    if parsed.scheme not in ("http", "https"):
        raise IntelError("UNSAFE_URL", f"只允许 HTTP/HTTPS: {parsed.scheme}")
    if parsed.username or parsed.password:
        raise IntelError("UNSAFE_URL", "URL 不得包含用户名或密码")
    hostname = strip_ipv6_brackets(parsed.hostname or "").lower()
    if not hostname or hostname == "localhost" or hostname.endswith(".localhost") or hostname.endswith(".local"):
        raise IntelError("UNSAFE_URL", f"非公网主机: {hostname}")
    if _is_ip(hostname):
        addresses = [hostname]
    else:
        addresses = await resolver(hostname)
    if not addresses or any(not is_public_address(a) for a in addresses):
        raise IntelError("UNSAFE_URL", f"目标解析到非公网地址: {', '.join(addresses) or hostname}")
    return parsed, addresses


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(strip_ipv6_brackets(value))
        return True
    except ValueError:
        return False


async def assert_public_url(raw: str, resolver: AddressResolver | None = None):
    url, _ = await resolve_public_url(raw, resolver)
    return url


def source_group_of(url: str) -> str:
    extracted = tldextract.extract(url)
    domain = getattr(extracted, "top_domain_under_public_suffix", None) or extracted.registered_domain or ""
    if not domain:
        raise IntelError("INVALID_INPUT", f"无法识别来源域: {url}")
    return domain.lower()