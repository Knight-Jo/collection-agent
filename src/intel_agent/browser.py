"""JavaScript page detection and optional browser rendering."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path
from typing import Literal

from .config import FetchConfig
from .models import IntelError
from .security import AddressResolver, resolve_public_url

RenderDecision = Literal["empty_body", "javascript_required", "app_shell"]

_JAVASCRIPT_REQUIRED = re.compile(
    r"(?:enable|require(?:s|d)?)\s+javascript|"
    r"javascript\s+(?:is\s+)?(?:disabled|required)|"
    r"请(?:启用|开启)\s*javascript|需要\s*javascript",
    re.I,
)
_SCRIPT = re.compile(r"<script\b", re.I)
_EMPTY_MOUNT = re.compile(
    r"<(?:div|main)[^>]+(?:id|class)=[\"'][^\"']*"
    r"(?:(?<![\w-])(?:root|app)(?![\w-])|__next)[^\"']*[\"']"
    r"[^>]*>\s*(?:loading|加载中|正在加载)?\s*</(?:div|main)>",
    re.I,
)
_CHALLENGE = re.compile(
    r"(?:recaptcha|hcaptcha|turnstile|cf-chl-|captcha|"
    r"verify\s+(?:that\s+)?you\s+are\s+(?:a\s+)?human|"
    r"人机验证|滑块验证)",
    re.I,
)
_BLOCKED_RESOURCE_TYPES = {"image", "media", "font", "eventsource"}
_ALLOWED_METHODS = {"GET", "HEAD", "OPTIONS"}
_DOM_QUIET_SCRIPT = """
window.__intelLastMutation = Date.now();
new MutationObserver(() => {
  window.__intelLastMutation = Date.now();
}).observe(document, {subtree: true, childList: true, characterData: true});
"""


@dataclass(frozen=True)
class RenderedPage:
    final_url: str
    html: str
    downloaded_bytes: int
    request_count: int


BrowserRender = Callable[[str, int], Awaitable[RenderedPage]]


@dataclass(frozen=True)
class BrowserAvailability:
    playwright: bool
    chromium: bool


@dataclass
class _RenderState:
    max_bytes: int
    request_count: int = 0
    downloaded_bytes: int = 0
    failure: IntelError | None = None


class BrowserRequestPolicy:
    """Validate browser network requests before Chromium connects."""

    def __init__(
        self,
        config: FetchConfig,
        resolver: AddressResolver | None = None,
    ):
        self.config = config
        self.resolver = resolver

    async def validate(
        self, url: str, method: str, resource_type: str
    ) -> bool:
        if resource_type in _BLOCKED_RESOURCE_TYPES:
            return False
        if method.upper() not in _ALLOWED_METHODS:
            raise IntelError(
                "UNSAFE_BROWSER_REQUEST",
                f"浏览器请求方法被阻止: {method.upper()}",
            )
        await resolve_public_url(url, self.resolver)
        return True


async def _start_playwright():
    from playwright.async_api import async_playwright

    return await async_playwright().start()


def browser_runtime_status() -> BrowserAvailability:
    """Report whether the optional Playwright driver and Chromium exist."""
    if find_spec("playwright") is None:
        return BrowserAvailability(playwright=False, chromium=False)
    try:
        from playwright.sync_api import sync_playwright

        playwright = sync_playwright().start()
        try:
            chromium = Path(playwright.chromium.executable_path).is_file()
        finally:
            playwright.stop()
    except Exception:
        chromium = False
    return BrowserAvailability(playwright=True, chromium=chromium)


class BrowserRenderer:
    """Lazily reuse one Chromium process with an isolated context per page."""

    def __init__(
        self,
        config: FetchConfig,
        resolver: AddressResolver | None = None,
    ):
        self.config = config
        self.policy = BrowserRequestPolicy(config, resolver)
        self._semaphore = asyncio.Semaphore(config.browser_concurrency)
        self._start_lock = asyncio.Lock()
        self._playwright = None
        self._browser = None

    async def __aenter__(self) -> BrowserRenderer:
        return self

    async def __aexit__(self, *_args) -> None:
        await self.close()

    async def _ensure_browser(self):
        if self._browser is not None:
            return self._browser
        if find_spec("playwright") is None:
            raise IntelError(
                "BROWSER_UNAVAILABLE", "未安装 Playwright 浏览器依赖"
            )
        async with self._start_lock:
            if self._browser is None:
                try:
                    self._playwright = await _start_playwright()
                    self._browser = await self._playwright.chromium.launch(
                        headless=True
                    )
                except Exception as error:
                    await self.close()
                    raise IntelError(
                        "BROWSER_UNAVAILABLE", f"Chromium 启动失败: {error}"
                    ) from error
        return self._browser

    async def close(self) -> None:
        browser, playwright = self._browser, self._playwright
        self._browser = None
        self._playwright = None
        if browser is not None:
            with suppress(Exception):
                await browser.close()
        if playwright is not None:
            with suppress(Exception):
                await playwright.stop()

    async def render(
        self, url: str, max_bytes: int | None = None
    ) -> RenderedPage:
        limit = min(
            max_bytes or self.config.browser_max_bytes,
            self.config.browser_max_bytes,
        )
        async with self._semaphore:
            browser = await self._ensure_browser()
            context = await browser.new_context(
                service_workers="block",
                accept_downloads=False,
                ignore_https_errors=False,
                locale="zh-CN",
            )
            state = _RenderState(max_bytes=limit)
            size_tasks: set[asyncio.Task] = set()
            try:
                await context.route("**/*", self._route_handler(state))
                await context.route_web_socket("**/*", self._websocket_handler)
                await context.add_init_script(_DOM_QUIET_SCRIPT)
                page = await context.new_page()
                page.on(
                    "requestfinished",
                    lambda request: self._track_size(
                        request, state, size_tasks
                    ),
                )
                try:
                    async with asyncio.timeout(
                        self.config.browser_timeout_seconds
                    ):
                        await page.goto(
                            url,
                            wait_until="domcontentloaded",
                            timeout=self.config.browser_timeout_seconds * 1000,
                        )
                        await page.wait_for_function(
                            "Date.now() - window.__intelLastMutation >= 500",
                            timeout=self.config.browser_timeout_seconds * 1000,
                        )
                        html = await page.content()
                except TimeoutError as error:
                    raise IntelError(
                        "RENDER_TIMEOUT", f"动态页面渲染超时: {url}"
                    ) from error
                except IntelError:
                    raise
                except Exception as error:
                    code = (
                        "RENDER_TIMEOUT"
                        if type(error).__name__ == "TimeoutError"
                        else "BROWSER_ERROR"
                    )
                    raise IntelError(
                        code, f"动态页面渲染失败: {error}"
                    ) from error
                if size_tasks:
                    await asyncio.gather(*size_tasks, return_exceptions=True)
                if state.failure is not None:
                    raise state.failure
                if len(html.encode("utf-8")) > limit:
                    raise IntelError("RENDER_LIMIT", "渲染 DOM 超过字节限制")
                rendered_text = re.sub(r"<[^>]+>", " ", html)
                if challenge_required(html, rendered_text):
                    raise IntelError(
                        "CHALLENGE_REQUIRED", "页面需要交互式人机验证"
                    )
                return RenderedPage(
                    final_url=page.url,
                    html=html,
                    downloaded_bytes=state.downloaded_bytes,
                    request_count=state.request_count,
                )
            finally:
                for task in size_tasks:
                    task.cancel()
                await context.close()

    def _route_handler(self, state: _RenderState) -> Callable:
        async def handle(route) -> None:
            request = route.request
            state.request_count += 1
            if state.request_count > self.config.browser_max_requests:
                state.failure = IntelError(
                    "RENDER_LIMIT", "浏览器请求数量超过限制"
                )
                await route.abort("blockedbyclient")
                return
            try:
                allowed = await self.policy.validate(
                    request.url, request.method, request.resource_type
                )
            except IntelError as error:
                if request.is_navigation_request():
                    state.failure = error
                await route.abort("blockedbyclient")
                return
            if not allowed:
                await route.abort("blockedbyclient")
                return
            await route.continue_()

        return handle

    async def _websocket_handler(self, route) -> None:
        await route.close(code=1008, reason="WebSocket collection disabled")

    def _track_size(
        self,
        request,
        state: _RenderState,
        tasks: set[asyncio.Task],
    ) -> None:
        async def track() -> None:
            try:
                sizes = await request.sizes()
                state.downloaded_bytes += int(sizes["responseBodySize"])
                if state.downloaded_bytes > state.max_bytes:
                    state.failure = IntelError(
                        "RENDER_LIMIT", "浏览器下载超过字节限制"
                    )
            except Exception:
                return

        task = asyncio.create_task(track())
        tasks.add(task)
        task.add_done_callback(tasks.discard)


def should_render_html(
    html: str, extracted_text: str
) -> RenderDecision | None:
    """Return why an HTML response needs JavaScript, if it looks like a shell."""
    if len("".join(extracted_text.split())) >= 200:
        return None
    if _JAVASCRIPT_REQUIRED.search(html):
        return "javascript_required"
    if not _SCRIPT.search(html) or not _EMPTY_MOUNT.search(html):
        return None
    return "empty_body" if not extracted_text.strip() else "app_shell"


def challenge_required(html: str, extracted_text: str) -> bool:
    """Detect an interactive anti-bot challenge that needs user input."""
    return bool(_CHALLENGE.search(f"{html}\n{extracted_text}"))
