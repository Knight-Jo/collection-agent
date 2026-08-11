"""Document fetch tests with fake fetcher."""

import pytest

import intel_agent.fetch as fetch_module
from intel_agent.fetch import (
    FetchedResponse,
    fetch_document,
    parse_http_response,
    pinned_fetch,
)
from intel_agent.models import IntelError


async def _public_resolver(hostname):
    return ["93.184.216.34"]


class _StreamingReader:
    def __init__(self, content_type: str, body: bytes):
        self.header = (
            f"HTTP/1.1 200 OK\r\nContent-Type: {content_type}\r\n\r\n"
        ).encode("ascii")
        self.body = body
        self.offset = 0
        self.downloaded_body_bytes = 0

    async def readuntil(self, _separator: bytes) -> bytes:
        return self.header

    async def read(self, size: int) -> bytes:
        chunk = self.body[self.offset : self.offset + size]
        self.offset += len(chunk)
        self.downloaded_body_bytes += len(chunk)
        return chunk

    def at_eof(self) -> bool:
        return self.offset >= len(self.body)


class _Writer:
    def write(self, _value: bytes) -> None:
        pass

    async def drain(self) -> None:
        pass

    def close(self) -> None:
        pass

    async def wait_closed(self) -> None:
        pass


@pytest.mark.asyncio
async def test_pinned_fetch_stops_html_stream_at_mime_aware_cap(monkeypatch):
    reader = _StreamingReader("text/html", b"0123456789")

    async def open_connection(*_args, **_kwargs):
        return reader, _Writer()

    monkeypatch.setattr(
        fetch_module.asyncio, "open_connection", open_connection
    )

    with pytest.raises(IntelError) as error:
        await pinned_fetch(
            "http://example.com/",
            None,
            "93.184.216.34",
            max_bytes=10,
            max_html_bytes=4,
        )

    assert error.value.code == "RESPONSE_TOO_LARGE"
    assert error.value.downloaded_bytes == reader.downloaded_body_bytes
    assert reader.downloaded_body_bytes == 4


@pytest.mark.asyncio
async def test_fetch_saves_document(cwd):
    html = "<html><head><title>测试新闻</title></head><body><p>关于测试主题的报道内容。</p></body></html>"

    async def fetcher(url, init, address):
        return FetchedResponse(
            status=200,
            headers={"content-type": "text/html"},
            body=html.encode(),
        )

    document, content, links = await fetch_document(
        cwd,
        "https://news.example.com/a",
        fetcher=fetcher,
        resolver=_public_resolver,
    )
    assert document.id.startswith("doc-")
    assert "测试主题" in content
    assert content.startswith("<untrusted_web_content>")
    assert document.source_group == "example.com"
    assert (cwd / document.raw_path).exists()
    assert (cwd / document.text_path).exists()

    # 幂等：重复抓取返回同一文档
    document2, _, _ = await fetch_document(
        cwd,
        "https://news.example.com/a",
        fetcher=fetcher,
        resolver=_public_resolver,
    )
    assert document2.id == document.id


@pytest.mark.asyncio
async def test_fetch_rejects_unsupported_content(cwd):
    async def fetcher(url, init, address):
        return FetchedResponse(
            status=200,
            headers={"content-type": "application/json"},
            body=b'{"x": 1}',
        )

    with pytest.raises(IntelError) as e:
        await fetch_document(
            cwd,
            "https://news.example.com/file.pdf",
            fetcher=fetcher,
            resolver=_public_resolver,
        )
    assert e.value.code == "UNSUPPORTED_CONTENT"


@pytest.mark.asyncio
async def test_fetch_rejects_too_large(cwd):
    async def fetcher(url, init, address):
        return FetchedResponse(
            status=200,
            headers={"content-type": "text/html"},
            body=b"x" * (5 * 1024 * 1024 + 10),
        )

    with pytest.raises(IntelError) as e:
        await fetch_document(
            cwd,
            "https://news.example.com/big",
            fetcher=fetcher,
            resolver=_public_resolver,
            max_bytes=1024,
        )
    assert e.value.code == "RESPONSE_TOO_LARGE"


@pytest.mark.asyncio
async def test_fetch_follows_validated_redirects(cwd):
    html = b"<html><body>redirected content</body></html>"
    calls = []

    async def fetcher(url, init, address):
        calls.append(url)
        if len(calls) == 1:
            return FetchedResponse(
                status=301,
                headers={"location": "https://news.example.com/final"},
                body=b"",
            )
        return FetchedResponse(
            status=200, headers={"content-type": "text/html"}, body=html
        )

    document, _, _ = await fetch_document(
        cwd,
        "https://news.example.com/start",
        fetcher=fetcher,
        resolver=_public_resolver,
    )
    assert document.final_url == "https://news.example.com/final"
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_fetch_redirect_to_private_blocked(cwd):
    async def fetcher(url, init, address):
        return FetchedResponse(
            status=301,
            headers={"location": "http://127.0.0.1/secret"},
            body=b"",
        )

    with pytest.raises(IntelError) as e:
        await fetch_document(
            cwd,
            "https://news.example.com/start",
            fetcher=fetcher,
            resolver=_public_resolver,
        )
    assert e.value.code == "UNSAFE_URL"


def test_parse_http_response_chunked():
    body = b"4\r\nWiki\r\n5\r\npedia\r\n0\r\n\r\n"
    raw = (
        b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nTransfer-Encoding: chunked\r\n\r\n"
        + body
    )
    response = parse_http_response(raw)
    assert response.status == 200
    assert response.body == b"Wikipedia"
    assert response.headers["content-type"] == "text/html"


def test_parse_http_response_rejects_truncated():
    with pytest.raises(IntelError) as e:
        parse_http_response(b"HTTP/1.1 200 OK\r\nNoHeaderTerminator")
    assert e.value.code == "NETWORK_ERROR"
