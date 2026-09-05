"""FetchService: validated, streaming acquisition (spec §7)."""

from __future__ import annotations

from datetime import UTC, datetime
from time import monotonic
from urllib.parse import urljoin

import httpx

from ..contracts.errors import DomainError
from ..contracts.resources import FetchRequest, FetchResult, ResourceOrigin
from ..runtime.config import FetchConfig
from ..storage.resources import ResourceStore
from .security import validate_public_url

MEDIA_PREFIXES = ("audio/", "video/", "image/")
MAX_REDIRECTS = 5
_SNIFF_BYTES = 512


class FetchService:
    def __init__(
        self,
        client: httpx.AsyncClient,
        resource_store: ResourceStore,
        config: FetchConfig,
    ) -> None:
        self.client = client
        self.resource_store = resource_store
        self.config = config

    async def fetch(self, request: FetchRequest) -> FetchResult:
        start = monotonic()
        if request.mode == "browser":
            raise DomainError(
                "BACKEND_UNAVAILABLE",
                "browser fetcher not configured",
                stage="fetch",
            )
        url = request.url
        await validate_public_url(url)
        warnings: list[str] = []
        final_url = url
        status_code: int | None = None
        for _ in range(MAX_REDIRECTS):
            response = await self._get(url, request)
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("location")
                await response.aclose()
                if not location:
                    raise DomainError(
                        "HTTP_ERROR", "redirect without location",
                        stage="fetch",
                    )
                url = urljoin(url, location)
                await validate_public_url(url)
                continue
            status_code = response.status_code
            final_url = str(response.url)
            if status_code >= 400:
                await response.aclose()
                code = (
                    "BLOCKED"
                    if status_code in (401, 403)
                    else "HTTP_ERROR"
                )
                raise DomainError(
                    code,
                    f"HTTP {status_code} for {final_url}",
                    stage="fetch",
                    safe_details={"status_code": status_code},
                )
            media_type = _media_type(response)
            max_bytes = _effective_limit(request, self.config, media_type)
            origin = ResourceOrigin(
                requested_url=request.url,
                final_url=final_url,
                acquired_at=datetime.now(UTC),
            )
            resource = await self.resource_store.write_stream(
                _bounded_bytes(response, max_bytes),
                origin=origin,
                media_type=media_type,
                max_bytes=max_bytes,
            )
            await response.aclose()
            return FetchResult(
                resource=resource,
                status_code=status_code,
                safe_headers=_safe_headers(response.headers),
                method="http",
                elapsed_ms=int((monotonic() - start) * 1000),
                warnings=warnings,
            )
        raise DomainError("HTTP_ERROR", "too many redirects", stage="fetch")

    async def _get(self, url: str, request: FetchRequest):
        try:
            return await self.client.send(
                self.client.build_request("GET", url, headers=request.headers),
                stream=True,
                follow_redirects=False,
                timeout=request.timeout_seconds,
            )
        except DomainError:
            raise
        except httpx.TimeoutException as error:
            raise DomainError(
                "TIMEOUT", f"fetch timed out: {url}", stage="fetch"
            ) from error
        except httpx.NetworkError as error:
            raise DomainError(
                "NETWORK_ERROR", f"network error: {url}", stage="fetch"
            ) from error


async def _bounded_bytes(response, max_bytes: int):
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > max_bytes:
            raise DomainError(
                "TOO_LARGE", f"response exceeds {max_bytes} bytes",
                stage="fetch",
            )
        yield chunk


def _media_type(response) -> str:
    content_type = response.headers.get("content-type", "")
    media_type = content_type.split(";")[0].strip().lower()
    return media_type or "application/octet-stream"


def _effective_limit(request, config, media_type) -> int:
    if request.max_bytes is not None:
        return request.max_bytes
    if request.allow_media and media_type.startswith(MEDIA_PREFIXES):
        return config.media_max_bytes
    return config.normal_max_bytes


def _safe_headers(headers) -> dict[str, str]:
    excluded = {"authorization", "cookie", "set-cookie", "proxy-authorization"}
    return {
        k: v for k, v in headers.items()
        if k.lower() not in excluded
    }
