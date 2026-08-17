"""Dynamic browser fallback tests."""

import asyncio
from types import SimpleNamespace

import pytest

import intel_agent.browser as browser_module
from intel_agent.browser import (
    BrowserRenderer,
    BrowserRequestPolicy,
    browser_runtime_status,
    challenge_required,
    should_render_html,
)
from intel_agent.config import FetchConfig
from intel_agent.models import IntelError


async def _public_resolver(_hostname: str) -> list[str]:
    return ["93.184.216.34"]


async def _private_resolver(_hostname: str) -> list[str]:
    return ["127.0.0.1"]


def test_static_article_with_scripts_does_not_require_browser():
    text = "公开信息" * 100
    html = f"<article>{text}</article><script src='/app.js'></script>"

    assert should_render_html(html, text) is None


def test_empty_app_shell_requires_browser():
    html = '<div id="root"></div><script src="/app.js"></script>'

    assert should_render_html(html, "") == "empty_body"


def test_javascript_placeholder_requires_browser():
    html = (
        "<noscript>Please enable JavaScript to continue</noscript>"
        "<script src='/app.js'></script>"
    )

    assert should_render_html(html, "") == "javascript_required"


def test_empty_static_page_does_not_start_browser():
    assert should_render_html("<html><body></body></html>", "") is None


def test_short_mounted_app_shell_requires_browser():
    html = (
        '<div id="app">Loading</div>'
        '<script type="module" src="/assets/index.js"></script>'
    )

    assert should_render_html(html, "Loading") == "app_shell"


def test_interactive_challenge_is_detected():
    html = (
        '<iframe src="https://challenges.cloudflare.com/turnstile"></iframe>'
    )

    assert challenge_required(html, "Verify you are human") is True


def test_normal_page_is_not_an_interactive_challenge():
    assert (
        challenge_required("<article>Public report</article>", "Public report")
        is False
    )


@pytest.mark.asyncio
async def test_browser_policy_blocks_private_request():
    policy = BrowserRequestPolicy(FetchConfig(), resolver=_private_resolver)

    with pytest.raises(IntelError) as raised:
        await policy.validate("http://metadata.example/latest", "GET", "xhr")

    assert raised.value.code == "UNSAFE_URL"


@pytest.mark.asyncio
async def test_browser_policy_blocks_mutating_methods():
    policy = BrowserRequestPolicy(FetchConfig(), resolver=_public_resolver)

    with pytest.raises(IntelError) as raised:
        await policy.validate("https://example.com/api", "POST", "fetch")

    assert raised.value.code == "UNSAFE_BROWSER_REQUEST"


@pytest.mark.asyncio
async def test_browser_policy_skips_heavy_and_streaming_resources():
    policy = BrowserRequestPolicy(FetchConfig(), resolver=_public_resolver)

    assert (
        await policy.validate("https://example.com/image.png", "GET", "image")
        is False
    )
    assert (
        await policy.validate(
            "https://example.com/events", "GET", "eventsource"
        )
        is False
    )


@pytest.mark.asyncio
async def test_renderer_reports_missing_playwright(monkeypatch):
    monkeypatch.setattr(browser_module, "find_spec", lambda _name: None)
    renderer = BrowserRenderer(
        FetchConfig(enable_browser_fallback=True), resolver=_public_resolver
    )

    with pytest.raises(IntelError) as raised:
        await renderer.render("https://example.com", 1024)

    assert raised.value.code == "BROWSER_UNAVAILABLE"


def test_browser_runtime_status_uses_install_list_without_starting_driver(
    monkeypatch,
):
    monkeypatch.setattr(browser_module, "find_spec", lambda _name: object())
    monkeypatch.setattr(
        browser_module,
        "_playwright_install_output",
        lambda: "chromium-123 /cache/ms-playwright/chromium-123",
    )

    status = browser_runtime_status()

    assert status.playwright is True
    assert status.chromium is True


@pytest.mark.asyncio
async def test_real_chromium_renders_local_javascript_fixture(monkeypatch):
    if not browser_runtime_status().chromium:
        pytest.skip("Playwright Chromium is not installed")

    html = b"""<!doctype html>
<div id="root"></div>
<script>document.getElementById("root").textContent = "rendered-smoke-token";</script>
"""

    async def handle(reader, writer):
        await reader.readuntil(b"\r\n\r\n")
        writer.write(
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/html; charset=utf-8\r\n"
            + f"Content-Length: {len(html)}\r\n".encode()
            + b"Connection: close\r\n\r\n"
            + html
        )
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    renderer = BrowserRenderer(
        FetchConfig(
            enable_browser_fallback=True,
            browser_timeout_seconds=5,
        ),
        resolver=_public_resolver,
    )

    async def allow_local_fixture(_url, _method, _resource_type):
        return True

    monkeypatch.setattr(renderer.policy, "validate", allow_local_fixture)
    try:
        async with server, renderer:
            rendered = await renderer.render(
                f"http://127.0.0.1:{port}/", 1024 * 1024
            )
    finally:
        server.close()
        await server.wait_closed()

    assert "rendered-smoke-token" in rendered.html


class _FakePage:
    url = "https://example.com/app"

    def __init__(self):
        self.handlers = {}

    def on(self, event, handler):
        self.handlers[event] = handler

    async def goto(self, _url, **_kwargs):
        return SimpleNamespace(status=200)

    async def wait_for_function(self, _expression, **_kwargs):
        return None

    async def content(self):
        return "<html><main>Rendered public report</main></html>"


class _FakeContext:
    def __init__(self):
        self.closed = False

    async def route(self, _pattern, _handler):
        return None

    async def route_web_socket(self, _pattern, _handler):
        return None

    async def add_init_script(self, _script):
        return None

    async def new_page(self):
        return _FakePage()

    async def close(self):
        self.closed = True


class _FakeBrowser:
    def __init__(self):
        self.contexts = []
        self.closed = False

    async def new_context(self, **_kwargs):
        context = _FakeContext()
        self.contexts.append(context)
        return context

    async def close(self):
        self.closed = True


class _FakePlaywright:
    def __init__(self):
        self.browser = _FakeBrowser()
        self.launches = 0
        self.stopped = False
        self.chromium = self

    async def launch(self, **_kwargs):
        self.launches += 1
        return self.browser

    async def stop(self):
        self.stopped = True


@pytest.mark.asyncio
async def test_renderer_reuses_browser_and_closes_page_contexts(monkeypatch):
    fake = _FakePlaywright()
    monkeypatch.setattr(browser_module, "find_spec", lambda _name: object())

    async def start_playwright():
        return fake

    monkeypatch.setattr(browser_module, "_start_playwright", start_playwright)
    renderer = BrowserRenderer(
        FetchConfig(enable_browser_fallback=True), resolver=_public_resolver
    )

    async with renderer:
        first = await renderer.render("https://example.com/app", 4096)
        second = await renderer.render("https://example.com/app", 4096)

    assert first.html == second.html
    assert first.final_url == "https://example.com/app"
    assert fake.launches == 1
    assert len(fake.browser.contexts) == 2
    assert all(context.closed for context in fake.browser.contexts)
    assert fake.browser.closed is True
    assert fake.stopped is True
