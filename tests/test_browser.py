"""Dynamic browser fallback tests."""

from intel_agent.browser import challenge_required, should_render_html


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
    assert challenge_required("<article>Public report</article>", "Public report") is False
