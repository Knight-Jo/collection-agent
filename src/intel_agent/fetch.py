"""Secure document fetching with DNS pinning (port of fetch.ts)."""

from __future__ import annotations

import asyncio
import re
import ssl
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit, urlunsplit

from . import document_extract as _document_extract
from .document_extract import (
    decode_body,
    extract_docx_text,
    extract_html,
    extract_outbound_links,
    extract_pdf_text,
)
from .models import IntelDocument, IntelError, is_valid_calendar_date
from .security import AddressResolver, resolve_public_url, source_group_of
from .source import source_type_for_domain
from .storage import (
    read_json,
    sha256,
    verify_document_integrity,
    write_file_atomic,
    write_json_atomic,
)

publication_date = _document_extract.publication_date

# 5MB comfortably covers long-form articles/reports while bounding memory and
# the attack surface for hostile servers; 25s balances slow sites against the
# LLM turn budget; 5 redirects bounds loop chains without blocking legit pages.
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_TIMEOUT_MS = 25_000
REDIRECT_STATUSES = {301, 302, 303, 307, 308}
MAX_REDIRECTS = 5
USER_AGENT = "pi-intelligence-collector/1.0"


@dataclass
class FetchedResponse:
    status: int
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""


@dataclass
class BodyProgress:
    downloaded_bytes: int = 0


FetchLike = Callable[[str, dict | None, str], Awaitable[FetchedResponse]]
BeforeFetch = Callable[[str], Awaitable[None]]


def canonicalize_url(raw: str) -> str:
    # Tracking params (utm_*/spm/from/source) produce distinct URLs for the
    # same content; stripping and sorting them gives one canonical form so
    # dedup and content-addressed IDs are stable across sessions.
    parsed = urlsplit(raw)
    params = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if not re.match(
            r"^(?:utm_|spm$|from$|source$|fbclid$|gclid$|dclid$|msclkid$|mc_cid$|mc_eid$|_ga$|igshid$)",
            k,
            flags=re.I,
        )
    ]
    params.sort()
    query = urlencode(params)
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower()
    try:
        port = parsed.port
    except ValueError:
        port = None
    default_port = (scheme == "http" and port == 80) or (
        scheme == "https" and port == 443
    )
    host = f"[{hostname}]" if ":" in hostname else hostname
    netloc = host if port is None or default_port else f"{host}:{port}"
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/") or "/"
    return urlunsplit((scheme, netloc, path, query, ""))


def injection_warnings(text: str) -> list[str]:
    """Flag lines that look like prompt-injection attempts.

    Fetched content is later shown to the LLM inside <untrusted_web_content>;
    malicious pages try to hijack the agent with instruction-like text. The
    patterns are heuristic (Chinese/English variants of "ignore instructions"
    / "run commands" / "use tools") — false positives are acceptable, false
    negatives are not eliminated, so this is an alert, not a sanitizer.
    """
    patterns = [
        re.compile(r"忽略(?:此前|之前|以上).{0,12}指令", re.I),
        re.compile(r"(?:执行|运行).{0,8}(?:命令|代码)", re.I),
        re.compile(r"(?:调用|使用).{0,8}(?:工具|tool)", re.I),
        re.compile(r"ignore (?:all )?(?:previous|prior) instructions", re.I),
    ]
    return [
        line[:160]
        for line in text.split("\n")
        if any(p.search(line) for p in patterns)
    ]


async def pinned_fetch(
    input_url: str,
    init: dict | None,
    address: str,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_html_bytes: int | None = None,
    body_progress: BodyProgress | None = None,
) -> FetchedResponse:
    """DNS-pinned TCP/TLS fetch: connect to the validated public IP while
    keeping the original hostname for TLS SNI."""
    parsed = urlparse(input_url)
    https = parsed.scheme == "https"
    port = parsed.port or (443 if https else 80)
    ssl_ctx = ssl.create_default_context() if https else None
    reader, writer = await asyncio.open_connection(
        address,
        port,
        ssl=ssl_ctx,
        server_hostname=parsed.hostname if https else None,
    )
    try:
        path = f"{parsed.path or '/'}{('?' + parsed.query) if parsed.query else ''}"
        extra_headers = "".join(
            f"{key}: {value}\r\n"
            for key, value in (init or {}).get("headers", {}).items()
            if "\r" not in key
            and "\n" not in key
            and "\r" not in value
            and "\n" not in value
        )
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {parsed.hostname}{f':{port}' if port not in (80, 443) else ''}\r\n"
            f"User-Agent: {USER_AGENT}\r\n"
            "Accept: text/html,application/xhtml+xml,application/pdf,text/plain,*/*;q=0.8\r\n"
            f"{extra_headers}"
            "Connection: close\r\n\r\n"
        )
        writer.write(request.encode("latin-1"))
        await writer.drain()
        try:
            raw_head = await reader.readuntil(b"\r\n\r\n")
        except (
            asyncio.IncompleteReadError,
            asyncio.LimitOverrunError,
        ) as error:
            raise IntelError("NETWORK_ERROR", "响应头不完整") from error
        status, headers = _parse_http_head(raw_head)
        content_type = headers.get("content-type", "").lower()
        generic_content = content_type.split(";", 1)[0].strip() in {
            "",
            "application/octet-stream",
            "binary/octet-stream",
        }
        html_path = Path(parsed.path).suffix.lower() in {".htm", ".html"}
        body_limit = max_bytes
        if max_html_bytes is not None and (
            re.match(
                r"^(?:text/html|application/xhtml\+xml)(?:;|$)",
                content_type,
            )
            or (generic_content and html_path)
        ):
            body_limit = min(body_limit, max_html_bytes)
        body = await _read_response_body(
            reader, headers, body_limit, body_progress
        )
    finally:
        writer.close()
        with suppress(Exception):
            await writer.wait_closed()
    return FetchedResponse(status=status, headers=headers, body=body)


def _parse_http_head(raw: bytes) -> tuple[int, dict[str, str]]:
    if not raw.endswith(b"\r\n\r\n"):
        raise IntelError("NETWORK_ERROR", "响应头不完整")
    lines = raw[:-4].decode("latin-1").split("\r\n")
    status_match = re.match(r"^HTTP/\d\.\d (\d{3})", lines[0])
    if not status_match:
        raise IntelError("NETWORK_ERROR", "响应状态无效")
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()
    return int(status_match.group(1)), headers


async def _read_exact_body(
    reader,
    size: int,
    downloaded: int = 0,
    body_progress: BodyProgress | None = None,
) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        try:
            chunk = await reader.read(min(65_536, remaining))
        except (TimeoutError, OSError, asyncio.IncompleteReadError) as error:
            partial = getattr(error, "partial", b"")
            raise IntelError(
                "NETWORK_ERROR",
                "响应正文读取失败",
                downloaded_bytes=(
                    downloaded + size - remaining + len(partial)
                ),
            ) from error
        if not chunk:
            raise IntelError(
                "NETWORK_ERROR",
                "响应正文不完整",
                downloaded_bytes=downloaded + size - remaining,
            )
        chunks.append(chunk)
        remaining -= len(chunk)
        if body_progress is not None:
            body_progress.downloaded_bytes += len(chunk)
    return b"".join(chunks)


async def _read_framing(reader, size: int, downloaded: int) -> bytes:
    try:
        return await _read_exact_body(reader, size)
    except IntelError as error:
        raise IntelError(
            error.code,
            str(error),
            downloaded_bytes=downloaded,
        ) from error


async def _read_chunked_body(
    reader, max_bytes: int, body_progress: BodyProgress | None = None
) -> bytes:
    chunks: list[bytes] = []
    downloaded = 0
    while True:
        try:
            size_line = await reader.readuntil(b"\r\n")
            size = int(size_line[:-2].split(b";", 1)[0], 16)
        except (
            ValueError,
            TimeoutError,
            OSError,
            asyncio.IncompleteReadError,
            asyncio.LimitOverrunError,
        ) as error:
            raise IntelError(
                "NETWORK_ERROR",
                "分块响应不完整",
                downloaded_bytes=downloaded,
            ) from error
        if size == 0:
            await _read_framing(reader, 2, downloaded)
            return b"".join(chunks)
        remaining = max_bytes - downloaded
        if size > remaining:
            if remaining:
                await _read_exact_body(
                    reader, remaining, downloaded, body_progress
                )
                downloaded += remaining
            raise IntelError(
                "RESPONSE_TOO_LARGE",
                f"响应超过 {max_bytes} 字节",
                downloaded_bytes=downloaded,
            )
        chunk = await _read_exact_body(reader, size, downloaded, body_progress)
        terminator = await _read_framing(reader, 2, downloaded + size)
        if terminator != b"\r\n":
            raise IntelError(
                "NETWORK_ERROR",
                "分块响应不完整",
                downloaded_bytes=downloaded + size,
            )
        chunks.append(chunk)
        downloaded += size


async def _read_response_body(
    reader,
    headers: dict[str, str],
    max_bytes: int,
    body_progress: BodyProgress | None = None,
) -> bytes:
    if re.search(r"chunked", headers.get("transfer-encoding", ""), re.I):
        return await _read_chunked_body(reader, max_bytes, body_progress)
    content_length = headers.get("content-length")
    if content_length is not None:
        try:
            size = int(content_length)
        except ValueError as error:
            raise IntelError("NETWORK_ERROR", "Content-Length 无效") from error
        if size < 0:
            raise IntelError("NETWORK_ERROR", "Content-Length 无效")
        if size > max_bytes:
            raise IntelError(
                "RESPONSE_TOO_LARGE",
                f"响应超过 {max_bytes} 字节",
            )
        return await _read_exact_body(
            reader, size, body_progress=body_progress
        )
    chunks: list[bytes] = []
    downloaded = 0
    while downloaded < max_bytes:
        try:
            chunk = await reader.read(min(65_536, max_bytes - downloaded))
        except (TimeoutError, OSError, asyncio.IncompleteReadError) as error:
            partial = getattr(error, "partial", b"")
            raise IntelError(
                "NETWORK_ERROR",
                "响应正文读取失败",
                downloaded_bytes=downloaded + len(partial),
            ) from error
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        downloaded += len(chunk)
        if body_progress is not None:
            body_progress.downloaded_bytes += len(chunk)
    try:
        extra = await reader.read(1)
    except (TimeoutError, OSError, asyncio.IncompleteReadError) as error:
        partial = getattr(error, "partial", b"")
        raise IntelError(
            "NETWORK_ERROR",
            "响应正文读取失败",
            downloaded_bytes=downloaded + len(partial),
        ) from error
    if not extra:
        return b"".join(chunks)
    if body_progress is not None:
        body_progress.downloaded_bytes += len(extra)
    raise IntelError(
        "RESPONSE_TOO_LARGE",
        f"响应超过 {max_bytes} 字节",
        downloaded_bytes=downloaded + len(extra),
    )


async def httpx_fallback_fetch(
    input_url: str,
    _init: dict | None,
    _address: str,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> FetchedResponse:
    """httpx fallback for WAF/Cloudflare sites; trades away DNS pinning (low-risk pages only)."""
    import httpx

    async with httpx.AsyncClient(
        timeout=20.0, follow_redirects=False
    ) as client:
        response = await client.get(
            input_url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/pdf,text/plain,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
            },
        )
        body = response.content
        if len(body) > max_bytes:
            raise IntelError(
                "RESPONSE_TOO_LARGE",
                f"响应超过 {max_bytes} 字节",
                downloaded_bytes=len(body),
            )
        return FetchedResponse(
            status=response.status_code,
            headers={k.lower(): v for k, v in response.headers.items()},
            body=body,
        )


def parse_http_response(
    raw: bytes, max_bytes: int = DEFAULT_MAX_BYTES
) -> FetchedResponse:
    separator = raw.find(b"\r\n\r\n")
    if separator < 0:
        raise IntelError("NETWORK_ERROR", "响应头不完整")
    status, headers = _parse_http_head(raw[: separator + 4])
    body = raw[separator + 4 :]
    downloaded_body_bytes = len(body)
    if re.search(r"chunked", headers.get("transfer-encoding", ""), re.I):
        body = decode_chunked(body)
    if len(body) > max_bytes:
        raise IntelError(
            "RESPONSE_TOO_LARGE",
            f"响应超过 {max_bytes} 字节",
            downloaded_bytes=downloaded_body_bytes,
        )
    return FetchedResponse(status=status, headers=headers, body=body)


def decode_chunked(raw: bytes) -> bytes:
    chunks: list[bytes] = []
    offset = 0
    while offset < len(raw):
        line_end = raw.find(b"\r\n", offset)
        if line_end < 0:
            raise IntelError("NETWORK_ERROR", "分块响应不完整")
        size = int(raw[offset:line_end].split(b";", 1)[0].decode("ascii"), 16)
        offset = line_end + 2
        if size == 0:
            return b"".join(chunks)
        if offset + size + 2 > len(raw):
            raise IntelError("NETWORK_ERROR", "分块响应不完整")
        chunks.append(raw[offset : offset + size])
        offset += size + 2
    raise IntelError("NETWORK_ERROR", "分块响应缺少结束标记")


async def fetch_with_validated_redirects(
    raw_url: str,
    fetcher: FetchLike,
    resolver: AddressResolver | None,
    max_bytes: int,
    request_init: dict | None = None,
    before_fetch: BeforeFetch | None = None,
) -> tuple[FetchedResponse, object]:
    """Fetch following redirects, re-validating every hop as a public URL.

    A redirect target is attacker-controlled: without re-running
    resolve_public_url on each Location, a safe-looking first hop could land
    on an internal IP (SSRF via redirect). MAX_REDIRECTS bounds loop chains.
    """
    current_url, addresses = await resolve_public_url(raw_url, resolver)
    for redirects in range(MAX_REDIRECTS + 1):
        current_url_string = _url_string(current_url)
        if before_fetch is not None:
            await before_fetch(current_url_string)
        response = await fetcher(
            current_url_string,
            request_init if redirects == 0 else None,
            addresses[0],
        )
        if response.status not in REDIRECT_STATUSES:
            return response, current_url
        if redirects >= MAX_REDIRECTS:
            raise IntelError("NETWORK_ERROR", "重定向次数超过限制")
        location = response.headers.get("location")
        if not location:
            raise IntelError("NETWORK_ERROR", "重定向响应缺少 Location")
        from urllib.parse import urljoin

        current_url, addresses = await resolve_public_url(
            urljoin(_url_string(current_url), location), resolver
        )
    raise IntelError("NETWORK_ERROR", "重定向次数超过限制")


def _url_string(parsed) -> str:
    return parsed.geturl() if hasattr(parsed, "geturl") else str(parsed)


async def fetch_document(
    cwd: Path,
    raw_url: str,
    fetcher: FetchLike | None = None,
    resolver: AddressResolver | None = None,
    max_bytes: int | None = None,
) -> tuple[IntelDocument, str, list[dict]]:
    max_bytes = max_bytes or DEFAULT_MAX_BYTES
    fetcher = fetcher or (lambda u, i, a: pinned_fetch(u, i, a, max_bytes))
    try:
        async with asyncio.timeout(DEFAULT_TIMEOUT_MS / 1000):
            response, final_url = await fetch_with_validated_redirects(
                raw_url, fetcher, resolver, max_bytes
            )
    except TimeoutError as error:
        raise IntelError("NETWORK_ERROR", f"抓取超时: {raw_url}") from error
    except IntelError:
        raise
    except Exception as error:
        raise IntelError("NETWORK_ERROR", f"抓取失败: {error}") from error
    if response.status != 200:
        raise IntelError("NETWORK_ERROR", f"抓取失败: HTTP {response.status}")
    content_type = response.headers.get("content-type", "").lower()
    allowed = r"^(?:text/html|application/xhtml\+xml|text/plain|application/pdf|application/msword|application/vnd\.openxmlformats-officedocument\.wordprocessingml\.document)(?:;|$)"
    if not re.match(allowed, content_type):
        raise IntelError(
            "UNSUPPORTED_CONTENT",
            f"不支持的内容类型: {content_type or 'unknown'}",
        )
    raw_bytes = response.body
    if len(raw_bytes) > max_bytes:
        raise IntelError(
            "RESPONSE_TOO_LARGE",
            f"响应超过 {max_bytes} 字节",
            downloaded_bytes=len(raw_bytes),
        )
    raw_text = decode_body(raw_bytes, content_type)
    is_html = bool(re.search(r"html|xhtml", content_type))
    is_pdf = "pdf" in content_type
    is_docx = "officedocument" in content_type or "msword" in content_type
    if is_html:
        extracted = extract_html(raw_text)
    elif is_pdf:
        try:
            text = extract_pdf_text(raw_bytes)
        except Exception as error:
            raise IntelError(
                "NETWORK_ERROR", f"PDF 文本提取失败: {error}"
            ) from error
        extracted = {
            "title": Path(urlparse(_url_string(final_url)).path).name,
            "text": text,
            "publish_time": None,
            "publish_time_source": "unknown",
        }
    elif is_docx:
        try:
            text = extract_docx_text(raw_bytes)
        except Exception as error:
            raise IntelError(
                "NETWORK_ERROR", f"Word 文本提取失败: {error}"
            ) from error
        extracted = {
            "title": Path(urlparse(_url_string(final_url)).path).name,
            "text": text,
            "publish_time": None,
            "publish_time_source": "unknown",
        }
    else:
        extracted = {
            "title": _url_string(final_url),
            "text": raw_text.replace("\r\n", "\n").strip(),
            "publish_time": None,
            "publish_time_source": "unknown",
        }
    outbound_links = (
        extract_outbound_links(raw_text, _url_string(final_url))
        if is_html
        else []
    )
    if not extracted["publish_time"]:
        url_match = re.search(
            r"/(20\d{2})[-/]?(\d{2})[-/]?(\d{2})/", _url_string(final_url)
        )
        if url_match and is_valid_calendar_date(
            f"{url_match.group(1)}-{url_match.group(2)}-{url_match.group(3)}"
        ):
            extracted["publish_time"] = (
                f"{url_match.group(1)}-{url_match.group(2)}-{url_match.group(3)}"
            )
            extracted["publish_time_source"] = "unknown"
    canonical_url = canonicalize_url(_url_string(final_url))
    raw_hash = sha256(raw_bytes)
    document_id = f"doc-{sha256(f'{canonical_url}\n{raw_hash}')[:16]}"
    document_path = f"documents/{document_id}.json"
    if (cwd / "data/intel" / document_path).exists():
        existing = IntelDocument.model_validate(read_json(cwd, document_path))
        verify_document_integrity(cwd, existing)
        return (
            existing,
            f"<untrusted_web_content>\n{extracted['text']}\n</untrusted_web_content>",
            outbound_links,
        )
    raw_path = f"data/raw/{document_id}.raw"
    text_path = f"data/raw/{document_id}.txt"
    write_file_atomic(cwd, raw_path, raw_bytes)
    write_file_atomic(cwd, text_path, extracted["text"])
    hostname = urlparse(_url_string(final_url)).hostname or ""
    document = IntelDocument(
        id=document_id,
        requested_url=raw_url,
        final_url=_url_string(final_url),
        canonical_url=canonical_url,
        title=extracted["title"] or _url_string(final_url),
        content_type=content_type.split(";")[0],
        publish_time=extracted["publish_time"],
        publish_time_source=extracted["publish_time_source"],
        collected_at=_now(),
        source_type=source_type_for_domain(hostname),
        source_group=source_group_of(_url_string(final_url)),
        raw_path=raw_path,
        raw_sha256=raw_hash,
        text_path=text_path,
        text_sha256=sha256(extracted["text"]),
        injection_warnings=injection_warnings(extracted["text"]),
    )
    write_json_atomic(cwd, document_path, document.model_dump())
    return (
        document,
        f"<untrusted_web_content>\n{extracted['text']}\n</untrusted_web_content>",
        outbound_links,
    )


def _now() -> str:
    from datetime import datetime

    return datetime.now(UTC).isoformat()
