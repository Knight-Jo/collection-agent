"""JavaScript page detection and optional browser rendering."""

from __future__ import annotations

import re
from typing import Literal

RenderDecision = Literal[
    "empty_body", "javascript_required", "app_shell"
]

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
