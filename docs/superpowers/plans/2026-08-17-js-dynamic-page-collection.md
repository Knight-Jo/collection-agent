# JS Dynamic Page Collection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in, static-first Playwright fallback that extracts and archives public JavaScript-rendered pages without weakening the existing evidence and crawl controls.

**Architecture:** A new lazy `BrowserRenderer` runs Chromium only when a shared HTML-shell detector says static extraction is insufficient. Direct fetch and recursive crawl receive the same renderer callback, preserve the original HTTP response, archive rendered DOM separately, and pass the rendered HTML back through existing extraction. Playwright validates every outgoing URL before continuing it; production deployments declare an externally enforced isolated network mode, while the API reports both runtime availability and the configured mode.

**Tech Stack:** Python 3.12, asyncio, Pydantic, Playwright Python/Chromium, pytest/pytest-asyncio, Ruff, Pyright, uv, FastAPI, React/TypeScript/Bun.

## Global Constraints

- Static HTTP fetching remains the default and must not start Chromium for usable HTML or non-HTML resources.
- Browser collection is limited to public HTTP/HTTPS pages that require no login.
- Allow GET, HEAD, and CORS preflight OPTIONS; block POST, WebSocket, EventSource, downloads, private addresses, local schemes, and interactive CAPTCHA solving.
- Preserve robots checks, task cancellation, crawl concurrency, byte limits, raw source hashes, rendered DOM hashes, and evidence integrity.
- Playwright is an optional dependency and browser absence must degrade to an explicit unavailable state.
- Use existing storage, extraction, URL security, crawl, and SSE patterns; do not add another queue, browser service, or Agent tool.
- Production comments and docstrings are English. Existing user-facing error messages remain Chinese where appropriate.
- Use `uv` only for Python dependency changes and Bun 1.3.14 for the frontend.

---

### Task 1: Browser configuration and document provenance

**Files:**
- Modify: `src/intel_agent/config.py`
- Modify: `src/intel_agent/models.py`
- Modify: `src/intel_agent/storage.py`
- Modify: `config.example.yaml`
- Test: `tests/test_document.py`
- Test: `tests/test_main.py`

**Interfaces:**
- Produces: `FetchConfig.enable_browser_fallback`, `browser_network_mode`, `browser_timeout_seconds`, `browser_max_requests`, `browser_max_bytes`, and `browser_concurrency`.
- Produces: backward-compatible `IntelDocument.collection_method`, `rendered_path`, `rendered_sha256`, and `render_error` fields.
- Produces: `CrawlEntry.render_reason` and `render_error` fields.

- [ ] **Step 1: Write failing configuration and integrity tests**

Add tests equivalent to:

```python
def test_browser_fetch_config_defaults_are_safe():
    config = FetchConfig()
    assert config.enable_browser_fallback is False
    assert config.browser_network_mode == "validated"
    assert config.browser_concurrency == 1


def test_rendered_document_integrity_checks_rendered_dom(cwd):
    document = make_document(cwd, "rendered text")
    rendered_path = f"data/raw/{document.id}.rendered.html"
    write_file_atomic(cwd, rendered_path, "<main>rendered text</main>")
    rendered = document.model_copy(
        update={
            "collection_method": "browser",
            "rendered_path": rendered_path,
            "rendered_sha256": sha256("<main>rendered text</main>"),
        }
    )
    with pytest.raises(IntelError, match="元数据不匹配"):
        verify_document_integrity(cwd, rendered)
```

Also verify old document JSON without the new fields still validates as `collection_method="http"`.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest tests/test_document.py tests/test_main.py -q
```

Expected: FAIL because browser configuration and provenance fields do not exist.

- [ ] **Step 3: Add minimal models and integrity derivation**

Implement these fields:

```python
class FetchConfig(BaseModel):
    enable_httpx_fallback: bool = True
    enable_browser_fallback: bool = False
    browser_network_mode: Literal["validated", "isolated"] = "validated"
    browser_timeout_seconds: float = Field(default=15.0, gt=0)
    browser_max_requests: int = Field(default=40, ge=1)
    browser_max_bytes: int = Field(default=20_971_520, ge=1)
    browser_concurrency: int = Field(default=1, ge=1)
```

Add to `IntelDocument`:

```python
collection_method: Literal["http", "browser"] = "http"
rendered_path: str | None = None
rendered_sha256: str | None = None
render_error: str | None = None
```

Add to `CrawlEntry`:

```python
render_reason: str | None = None
render_error: str | None = None
```

Change integrity ID derivation to append `\n{rendered_sha256}` only for browser documents, require the rendered path/hash pair together, and verify the rendered file hash.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the Step 2 command and expect all selected tests to pass.

- [ ] **Step 5: Commit**

```bash
git add src/intel_agent/config.py src/intel_agent/models.py src/intel_agent/storage.py config.example.yaml tests/test_document.py tests/test_main.py
git commit -m "feat(browser): add rendering configuration and provenance"
```

### Task 2: Shared dynamic-shell detection

**Files:**
- Create: `src/intel_agent/browser.py`
- Create: `tests/test_browser.py`

**Interfaces:**
- Produces: `RenderDecision = Literal["empty_body", "javascript_required", "app_shell"] | None`.
- Produces: `should_render_html(html: str, extracted_text: str) -> RenderDecision`.
- Produces: `challenge_required(html: str, extracted_text: str) -> bool`.

- [ ] **Step 1: Write failing detector tests**

Cover a useful article containing scripts, an empty root shell, an explicit JavaScript warning, an empty HTML page without scripts, and a CAPTCHA page:

```python
def test_static_article_does_not_require_browser():
    html = (
        "<article>"
        + "公开信息" * 100
        + "</article><script src='/app.js'></script>"
    )
    assert should_render_html(html, "公开信息" * 100) is None


def test_empty_app_shell_requires_browser():
    html = '<div id="root"></div><script src="/app.js"></script>'
    assert should_render_html(html, "") == "empty_body"


def test_javascript_placeholder_requires_browser():
    html = "<noscript>Please enable JavaScript to continue</noscript><script src='/app.js'></script>"
    assert should_render_html(html, "") == "javascript_required"


def test_interactive_challenge_is_detected():
    html = (
        '<iframe src="https://challenges.cloudflare.com/turnstile"></iframe>'
    )
    assert challenge_required(html, "Verify you are human") is True
```

- [ ] **Step 2: Run detector tests and verify RED**

```bash
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest tests/test_browser.py -q
```

Expected: collection error because `intel_agent.browser` does not exist.

- [ ] **Step 3: Implement the smallest stable heuristic**

Use compiled case-insensitive patterns for explicit JavaScript placeholders, common empty mount elements (`root`, `app`, `__next`), script presence, and interactive challenge markers. Return `None` whenever normalized extracted text contains at least 200 characters. Do not add framework-specific JSON parsers.

- [ ] **Step 4: Run detector tests and verify GREEN**

Run the Step 2 command and expect all detector tests to pass.

- [ ] **Step 5: Commit**

```bash
git add src/intel_agent/browser.py tests/test_browser.py
git commit -m "feat(browser): detect JavaScript-only page shells"
```

### Task 3: Optional Playwright renderer and request policy

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `src/intel_agent/browser.py`
- Modify: `tests/test_browser.py`

**Interfaces:**
- Produces: immutable `RenderedPage(final_url: str, html: str, downloaded_bytes: int, request_count: int)`.
- Produces: `BrowserAvailability(playwright: bool, chromium: bool)`.
- Produces: `browser_runtime_status() -> BrowserAvailability`.
- Produces: `BrowserRenderer(config: FetchConfig, resolver: AddressResolver | None = None)` async context manager.
- Produces: `BrowserRenderer.render(url: str, max_bytes: int | None = None) -> RenderedPage`.

- [ ] **Step 1: Read the test quality rules required by TDD**

Read `superpowers:test-driven-development/writing-good-tests.md` completely before changing the tests in this task.

- [ ] **Step 2: Write failing policy and lifecycle tests**

Use small fake route/request/context objects, not a mocked application service. Verify:

```python
async def test_browser_policy_blocks_private_request():
    policy = BrowserRequestPolicy(FetchConfig(), resolver=_private_resolver)
    with pytest.raises(IntelError) as raised:
        await policy.validate("http://metadata.internal/latest", "GET", "xhr")
    assert raised.value.code == "UNSAFE_URL"


async def test_browser_policy_blocks_mutating_methods():
    policy = BrowserRequestPolicy(FetchConfig(), resolver=_public_resolver)
    with pytest.raises(IntelError) as raised:
        await policy.validate("https://example.com/api", "POST", "fetch")
    assert raised.value.code == "UNSAFE_BROWSER_REQUEST"


async def test_renderer_reports_missing_playwright(monkeypatch):
    monkeypatch.setattr(browser_module, "find_spec", lambda _name: None)
    renderer = BrowserRenderer(FetchConfig(enable_browser_fallback=True))
    with pytest.raises(IntelError) as raised:
        await renderer.render("https://example.com", 1024)
    assert raised.value.code == "BROWSER_UNAVAILABLE"
```

Add a fake Playwright lifecycle test proving one browser launch is reused for two `render()` calls and each call closes its own context.

- [ ] **Step 3: Run renderer tests and verify RED**

Run:

```bash
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest tests/test_browser.py -q
```

Expected: FAIL because renderer types and request policy are missing.

- [ ] **Step 4: Add Playwright as an optional dependency**

Run:

```bash
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv add --optional browser "playwright>=1.48,<2"
```

Do not install Playwright in the default dependency set.

- [ ] **Step 5: Implement lazy rendering**

Implement a lazy async renderer that:

- imports `playwright.async_api` only on first render;
- launches one headless Chromium process and guards it with `browser_concurrency`;
- creates one non-persistent context per render with `service_workers="block"`, `accept_downloads=False`, and TLS validation enabled;
- routes `**/*`, calls `resolve_public_url`, allows only GET/HEAD/OPTIONS, and aborts image/media/font resources after recording their DOM URLs;
- routes WebSockets with `route_web_socket("**/*", ...)` and closes them before frames are exchanged;
- rejects requests after `browser_max_requests` and tracks encoded response bytes using `request.sizes()`;
- observes DOM mutations, waits for 500 ms of quiet after `DOMContentLoaded`, but never exceeds `browser_timeout_seconds`;
- rejects an interactive challenge with `IntelError("CHALLENGE_REQUIRED", ...)`;
- limits returned DOM bytes and closes the context in `finally`;
- closes the browser and Playwright driver on context manager exit or cancellation.

Keep `network_mode` informational in application code: `validated` means Playwright URL validation only; `isolated` means the deployment also supplies an outbound network sandbox.

- [ ] **Step 6: Run renderer tests and verify GREEN**

Run the Step 3 command and expect all tests to pass.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock src/intel_agent/browser.py tests/test_browser.py
git commit -m "feat(browser): add bounded Playwright renderer"
```

### Task 4: Consolidated raw and rendered document archive

**Files:**
- Modify: `src/intel_agent/fetch.py`
- Modify: `src/intel_agent/crawl.py`
- Modify: `tests/test_document.py`
- Modify: `tests/test_crawl.py`

**Interfaces:**
- Produces: `archive_document(cwd, requested_url, final_url, mime_type, raw, text, extraction_status, *, rendered_html=None, render_error=None, title="", publish_time=None, publish_time_source="unknown") -> IntelDocument` in `fetch.py`.
- Consumes: provenance and integrity rules from Task 1.

- [ ] **Step 1: Write failing dual-archive tests**

Add one direct helper test and one crawl-compatible test asserting:

```python
document = archive_document(
    cwd,
    "https://example.com/app",
    "https://example.com/app",
    "text/html",
    b'<div id="root"></div>',
    "rendered body",
    "complete",
    rendered_html="<main>rendered body</main>",
)
assert document.collection_method == "browser"
assert (cwd / document.raw_path).read_bytes() == b'<div id="root"></div>'
assert (
    cwd / document.rendered_path
).read_text() == "<main>rendered body</main>"
verify_document_integrity(cwd, document)
```

Also assert an HTTP-only document keeps its existing ID formula and no rendered path.

- [ ] **Step 2: Run archive tests and verify RED**

```bash
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest tests/test_document.py tests/test_crawl.py -q
```

Expected: FAIL because `archive_document` and rendered archive behavior are missing.

- [ ] **Step 3: Move the existing crawl archive implementation into `fetch.py`**

Create the public helper from the interface above. For browser documents derive the ID from:

```python
identity = f"{canonical_url}\n{raw_hash}\n{rendered_hash}"
```

Write rendered DOM to `data/raw/{document_id}.rendered.html`. Keep the existing static ID formula unchanged. Replace `_archive_resource` in `crawl.py` with the imported helper; do not keep two archive implementations.

- [ ] **Step 4: Run archive tests and verify GREEN**

Run the Step 2 command and expect all selected tests to pass.

- [ ] **Step 5: Commit**

```bash
git add src/intel_agent/fetch.py src/intel_agent/crawl.py tests/test_document.py tests/test_crawl.py
git commit -m "refactor(storage): unify rendered document archiving"
```

### Task 5: Static-first fallback in direct `web_fetch`

**Files:**
- Modify: `src/intel_agent/fetch.py`
- Modify: `src/intel_agent/agent.py`
- Modify: `tests/test_document.py`
- Modify: `tests/test_deep_crawl_workflow.py`

**Interfaces:**
- Consumes: `should_render_html`, `RenderedPage`, `BrowserRenderer.render`, and `archive_document`.
- Changes: `fetch_document(..., renderer: BrowserRender | None = None)`.
- Produces: `fetched_via="browser"` when the stored document uses browser collection.

- [ ] **Step 1: Write failing direct-fetch fallback tests**

Use a real static fake fetcher plus a fake renderer callback:

```python
async def renderer(url: str, max_bytes: int) -> RenderedPage:
    return RenderedPage(
        final_url=url,
        html="<html><main>" + "动态正文" * 100 + "</main></html>",
        downloaded_bytes=512,
        request_count=3,
    )


document, content, _ = await fetch_document(
    cwd,
    "https://example.com/app",
    fetcher=static_shell_fetcher,
    resolver=_public_resolver,
    renderer=renderer,
)
assert document.collection_method == "browser"
assert "动态正文" in content
```

Add a sibling test proving a useful static page never calls the renderer, plus an Agent tool test proving `fetched_via` is `browser`.

- [ ] **Step 2: Run direct-fetch tests and verify RED**

```bash
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest tests/test_document.py tests/test_deep_crawl_workflow.py -q
```

Expected: FAIL because `fetch_document` has no renderer callback and Agent does not wire it.

- [ ] **Step 3: Implement direct static-first fallback**

After static HTML extraction, call `should_render_html`. If it returns a reason and a renderer exists, render the final URL once, re-run `extract_html` and outbound-link extraction on the returned DOM, then archive the original response plus rendered DOM. If rendering fails, archive the original response with `extraction_status="unavailable"` and `render_error`, return it as `fetched_via="browser-failed"`, and rely on the existing evidence gate to prevent use as evidence.

In `_web_fetch`, create one lazy `BrowserRenderer(settings.fetch)` async context only when `enable_browser_fallback` is true and pass `renderer.render` into both pinned and httpx fallback calls. Set `fetched_via` from `document.collection_method`, retaining `httpx-fallback` when no browser was used.

- [ ] **Step 4: Run direct-fetch tests and verify GREEN**

Run the Step 2 command and expect all selected tests to pass.

- [ ] **Step 5: Commit**

```bash
git add src/intel_agent/fetch.py src/intel_agent/agent.py tests/test_document.py tests/test_deep_crawl_workflow.py
git commit -m "feat(fetch): render JavaScript shells on demand"
```

### Task 6: Static-first fallback in recursive crawl

**Files:**
- Modify: `src/intel_agent/crawl.py`
- Modify: `src/intel_agent/agent.py`
- Modify: `tests/test_crawl.py`
- Modify: `tests/test_deep_crawl_workflow.py`

**Interfaces:**
- Changes: `crawl_collect(..., renderer: BrowserRender | None = None)`.
- Consumes: Task 3 renderer callback and Task 4 archive helper.
- Produces: crawl entry render reason/error, rendered links, and browser byte accounting.

- [ ] **Step 1: Write failing crawler fallback tests**

Test an HTML shell whose fake renderer returns dynamic text and a new link:

```python
snapshot = await crawl_collect(
    cwd,
    task.id,
    ["https://example.com/app"],
    config=CrawlConfig(
        max_depth=1, obey_robots=False, per_host_delay_seconds=0
    ),
    fetcher=static_shell_fetcher,
    resolver=_public_resolver,
    renderer=fake_renderer,
)
entry = snapshot.entries[0]
assert entry.render_reason == "empty_body"
assert entry.extraction.status == "complete"
assert entry.extraction.processor == "html-browser"
assert any(
    item.parent_url == entry.canonical_url for item in snapshot.entries[1:]
)
```

Add tests for render byte limit, render failure persistence, cancellation, and a useful static page that does not render.

- [ ] **Step 2: Run crawler tests and verify RED**

```bash
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest tests/test_crawl.py tests/test_deep_crawl_workflow.py -q
```

Expected: FAIL because the crawler has no renderer callback or render state.

- [ ] **Step 3: Integrate rendering under existing crawl locks**

For HTML only, inspect the initial `ExtractionResult`. When rendering is required:

1. Store `entry.render_reason`.
2. Acquire the existing byte lock, calculate the remaining task bytes, and call the renderer with the smaller of remaining bytes and `settings.fetch.browser_max_bytes` supplied by the renderer.
3. Charge `RenderedPage.downloaded_bytes` to both entry and snapshot.
4. Run `extract_resource` on rendered UTF-8 HTML with MIME `text/html`.
5. Change a successful processor to `html-browser`, archive both bodies, and enqueue rendered links.
6. On stable browser errors, preserve the static raw document, set `entry.render_error`, and leave extraction unavailable; do not retry rendering in a loop.

Wrap the Agent `_crawl_collect` call in one lazy `BrowserRenderer` context when browser fallback is enabled so all dynamic pages in that crawl reuse one browser process.

- [ ] **Step 4: Run crawler tests and verify GREEN**

Run the Step 2 command and expect all selected tests to pass.

- [ ] **Step 5: Commit**

```bash
git add src/intel_agent/crawl.py src/intel_agent/agent.py tests/test_crawl.py tests/test_deep_crawl_workflow.py
git commit -m "feat(crawl): collect rendered page content"
```

### Task 7: Runtime status, frontend type, and operator documentation

**Files:**
- Modify: `src/intel_agent/web/schemas.py`
- Modify: `src/intel_agent/web/app.py`
- Modify: `tests/test_web_api.py`
- Modify: `web/src/types.ts`
- Modify: `web/src/pages/NewTaskPage.test.tsx`
- Modify: `README.md`
- Create: `docs/js-dynamic-page-deployment.md`

**Interfaces:**
- Produces: `/api/system.browser = {enabled, playwright, chromium, network_mode}`.
- Consumes: `browser_runtime_status()` and `FetchConfig` from earlier tasks.

- [ ] **Step 1: Write failing system-status tests**

Monkeypatch `browser_runtime_status` to return an available runtime and assert:

```python
assert response.json()["browser"] == {
    "enabled": True,
    "playwright": True,
    "chromium": True,
    "network_mode": "isolated",
}
```

Update frontend test fixtures to include the new browser object and add the matching TypeScript interface.

- [ ] **Step 2: Run API and frontend type tests and verify RED**

```bash
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest tests/test_web_api.py -q
cd web && bun run typecheck && bun run test
```

Expected: backend test fails because browser status is absent; TypeScript initially fails until the shared type and fixtures are updated.

- [ ] **Step 3: Implement runtime status and documentation**

Add `BrowserStatus` to the Pydantic schema and build it in `/api/system`. `browser_runtime_status()` must check both Python package availability and whether Playwright's Chromium executable path exists without launching a page.

Update README with:

```bash
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv sync --extra dev --extra browser
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run playwright install chromium
```

Document that `validated` mode performs application-level URL checks but retains DNS rebinding risk, while `isolated` mode is an operator assertion that the Chromium process has network-layer egress rules blocking host, private, link-local, IPv6 ULA, and cloud metadata ranges. Include non-root Chromium sandbox, seccomp, CPU/memory/process limits, read-only mounts, and a startup connectivity test as production requirements. State that interactive CAPTCHAs and login remain unsupported.

- [ ] **Step 4: Run focused verification and verify GREEN**

Run the Step 2 commands and expect all selected checks to pass.

- [ ] **Step 5: Commit**

```bash
git add src/intel_agent/web/schemas.py src/intel_agent/web/app.py tests/test_web_api.py web/src/types.ts web/src/pages/NewTaskPage.test.tsx README.md docs/js-dynamic-page-deployment.md
git commit -m "docs(browser): expose runtime and deployment requirements"
```

### Task 8: Full verification and dynamic-page smoke test

**Files:**
- Modify if required by failures: files already owned by Tasks 1–7 only

**Interfaces:**
- Consumes: complete browser fallback feature.
- Produces: clean repository verification evidence and one real Chromium smoke result when the browser binary can be installed.

- [ ] **Step 1: Install the optional browser environment**

```bash
mamba activate collection-agent-pydantic
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv sync --extra dev --extra browser
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run playwright install chromium
```

If the browser download is unavailable, record the exact command error; unit and integration tests must still pass without silently skipping runtime absence behavior.

- [ ] **Step 2: Run a local JavaScript smoke fixture**

Start a temporary local HTTP fixture whose script writes a unique paragraph into an empty `#root`. Use a test-only resolver that treats the fixture host as allowed, render it with `BrowserRenderer`, assert that the paragraph appears in returned HTML, and stop the fixture. Do not weaken production localhost blocking to make the smoke test pass.

- [ ] **Step 3: Run all backend verification**

```bash
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run ruff format --check .
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run ruff check .
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pyright
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv build
```

Expected: every command exits 0 with no test failures or type errors.

- [ ] **Step 4: Run all frontend verification**

```bash
cd web
bun install --frozen-lockfile
bun run test
bun run typecheck
bun run build
```

Expected: every command exits 0.

- [ ] **Step 5: Review scope and commit only necessary fixes**

```bash
git status --short
git diff --check
git diff --stat main...HEAD
```

Confirm no user-owned `.opencode/` or `graphify-out/` files entered the branch. If verification required a code fix, repeat its failing test first, implement the minimum correction, rerun the relevant focused test, then commit:

```bash
git add src/intel_agent tests web/src README.md config.example.yaml pyproject.toml uv.lock docs/js-dynamic-page-deployment.md
git commit -m "fix(browser): address verification findings"
```
