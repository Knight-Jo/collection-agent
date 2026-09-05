"""Public-network address validation (SSRF guards, spec §7.2)."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

from ..contracts.errors import DomainError

AddressResolver = Callable[[str], Awaitable[list[str]]]

# Every range below maps to a SSRF vector that fetch must never reach,
# regardless of DNS tricks or redirect chains (IPv4 + IPv6 + mapped).
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
    return (
        hostname[1:-1]
        if hostname.startswith("[") and hostname.endswith("]")
        else hostname
    )


def is_public_address(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(strip_ipv6_brackets(address))
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not any(ip in net for net in BLOCKED_NETWORKS)


async def default_resolver(hostname: str) -> list[str]:
    try:
        return sorted(
            {str(entry[4][0]) for entry in socket.getaddrinfo(hostname, None)}
        )
    except socket.gaierror:
        return []


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(strip_ipv6_brackets(value))
        return True
    except ValueError:
        return False


async def validate_public_url(
    url: str, resolver: AddressResolver | None = None
) -> tuple[object, list[str]]:
    """Validate a URL is safe to fetch and resolve it to public addresses.

    Gates (in order): scheme whitelist, embedded credentials, local hostnames,
    DNS resolution, and a public-address-only check over the exact addresses
    that will be connected to (DNS rebinding).
    """
    resolver = resolver or default_resolver
    try:
        parsed = urlsplit(url)
    except Exception as error:  # noqa: BLE001
        raise DomainError("UNSAFE_URL", f"invalid URL: {url}") from error
    if parsed.scheme not in ("http", "https"):
        raise DomainError("UNSAFE_URL", f"scheme not allowed: {parsed.scheme}")
    if parsed.username or parsed.password:
        raise DomainError("UNSAFE_URL", "URL must not embed credentials")
    hostname = strip_ipv6_brackets(parsed.hostname or "").lower()
    if (
        not hostname
        or hostname == "localhost"
        or hostname.endswith(".localhost")
        or hostname.endswith(".local")
    ):
        raise DomainError("UNSAFE_URL", f"non-public host: {hostname}")
    if _is_ip(hostname):
        addresses = [hostname]
    else:
        addresses = await resolver(hostname)
    if not addresses or any(not is_public_address(a) for a in addresses):
        raise DomainError(
            "UNSAFE_URL",
            f"target resolves to non-public address: "
            f"{', '.join(addresses) or hostname}",
        )
    return parsed, addresses
