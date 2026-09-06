"""SSRF-pinned HTTP transport (spec §7.2)."""

from __future__ import annotations

from collections.abc import AsyncIterable, AsyncIterator
from typing import Any, cast

import httpcore2
import httpx2

from ..contracts.errors import DomainError
from .security import (
    AddressResolver,
    default_resolver,
    is_public_address,
    strip_ipv6_brackets,
)


def _is_ip(value: str) -> bool:
    import ipaddress

    try:
        ipaddress.ip_address(strip_ipv6_brackets(value))
        return True
    except ValueError:
        return False


class PublicNetworkBackend(httpcore2.AnyIOBackend):
    """Validates the resolved connection target before every TCP connect.

    Overrides connect_tcp so that the exact address about to be connected to
    is checked for public-network status, closing the DNS-rebinding gap.
    """

    def __init__(self, resolver: AddressResolver | None = None) -> None:
        super().__init__()
        self._resolver = resolver or default_resolver

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options=None,
    ):
        hostname = strip_ipv6_brackets(host)
        if _is_ip(hostname):
            addresses = [hostname]
        else:
            addresses = await self._resolver(hostname)
        if not addresses or any(not is_public_address(a) for a in addresses):
            raise DomainError(
                "UNSAFE_URL",
                f"connection target is non-public: {host}",
                stage="fetch",
            )
        return await cast(Any, super()).connect_tcp(
            addresses[0], port, timeout, local_address, socket_options
        )


class _AsyncStream(httpx2.AsyncByteStream):
    def __init__(self, httpcore_stream: AsyncIterable[bytes]) -> None:
        self._stream = httpcore_stream

    async def __aiter__(self) -> AsyncIterator[bytes]:
        async for part in self._stream:
            yield part

    async def aclose(self) -> None:
        close = getattr(self._stream, "aclose", None)
        if close is not None:
            await close()


class PinnedTransport(httpx2.AsyncBaseTransport):
    """An httpx2 transport backed by a pool using PublicNetworkBackend."""

    def __init__(
        self,
        backend: PublicNetworkBackend | None = None,
        *,
        verify: bool = True,
        limits: httpx2.Limits | None = None,
        retries: int = 0,
    ) -> None:
        limits = limits or httpx2.Limits()
        ssl_context = httpx2.create_ssl_context(verify=verify, trust_env=False)
        self._pool = httpcore2.AsyncConnectionPool(
            ssl_context=ssl_context,
            max_connections=limits.max_connections,
            max_keepalive_connections=limits.max_keepalive_connections,
            keepalive_expiry=limits.keepalive_expiry,
            http1=True,
            http2=False,
            retries=retries,
            network_backend=backend or PublicNetworkBackend(),  # type: ignore[arg-type]
        )

    async def handle_async_request(
        self, request: httpx2.Request
    ) -> httpx2.Response:
        extensions = dict(request.extensions, follow_redirects=False)
        timeout = extensions.get("timeout")
        if isinstance(timeout, httpx2.Timeout):
            extensions["timeout"] = {
                "connect": timeout.connect,
                "read": timeout.read,
                "write": timeout.write,
                "pool": timeout.pool,
            }
        req = httpcore2.Request(
            method=request.method,
            url=httpcore2.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=extensions,
        )
        resp = await self._pool.handle_async_request(req)
        return httpx2.Response(
            status_code=resp.status,
            headers=resp.headers,
            stream=_AsyncStream(cast(AsyncIterable[bytes], resp.stream)),
            extensions=resp.extensions,
        )

    async def aclose(self) -> None:
        await self._pool.aclose()


def build_client(
    *,
    resolver: AddressResolver | None = None,
    timeout: float = 30.0,
    proxy: str | None = None,
) -> httpx2.AsyncClient:
    if proxy is not None:
        # Controlled egress proxy: FetchService still validates every target
        # URL is public via validate_public_url; the proxy is trusted egress
        # infrastructure that performs the actual connection.
        return httpx2.AsyncClient(
            proxy=proxy,
            trust_env=False,
            follow_redirects=False,
            timeout=timeout,
        )
    transport = PinnedTransport(PublicNetworkBackend(resolver))
    return httpx2.AsyncClient(
        transport=transport,
        trust_env=False,
        follow_redirects=False,
        timeout=timeout,
    )
