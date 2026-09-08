"""Heuristic junk-chunk detection for chunking and context selection.

Reference-heavy pages (Wikipedia above all) render their citation sections
and navigation boxes into markdown chunks that carry almost no prose but are
keyword-dense -- entity names, dates, URLs -- so lexical and hybrid retrieval
rank them above real body text and they crowd the token-bounded evidence
block. Observed on a 253-artifact run: three of the four cited "materials"
were link lists, and coverage collapsed to ``low`` despite 2300+ chunks.

Signals, each tuned so real prose survives (a paragraph with two inline
links stays; a short Chinese sentence with links stays):
- prose residue: strip links/URLs and the remaining text is tiny -> a link
  list wearing a sentence as a hat
- navigation lists: most non-empty lines are ``* [label](url)`` entries
- citation backlink soup: repeated ``[^](#cite_ref-...)`` / ``↑`` markers
- reference-entry lines: numbered ``↑`` / ``Retrieved <date>`` lines
"""

from __future__ import annotations

import re

_MD_LINK_RE = re.compile(r"\[[^\]]*\]\(\s*[^)]*\)|\]\(\s*https?://[^)]*\)")
_BARE_URL_RE = re.compile(r"https?://\S+")
_BACKLINK_RE = re.compile(r"\[\^\]\(#[^)]*\)|\bcite_ref\b|↑|edit source")
_NAV_LINE_RE = re.compile(r"^\s*[-*•]\s*\[[^\]]+\]\([^)]+\)\s*$")
# Numbered citation entries: "247. ↑\"...\"" or "... Retrieved 20 October ..."
_REF_LINE_RE = re.compile(
    r"^\s*\d+[.:]?\s*↑|↑\s*[\"“]|Retrieved \d{1,2} ", re.MULTILINE
)

# Repeated citation-backlink markers mean a references section.
MIN_BACKLINK_MARKERS = 3
# Two or more reference-entry lines = a references list, not prose.
MIN_REF_LINES = 2
# A lone reference-entry marker in a tiny fragment is archive residue.
TINY_REF_FRAGMENT_CHARS = 40
# >= 60% nav-style bullet lines out of at least 4 lines is a navigation box.
MIN_NAV_LINES = 4
NAV_LINE_RATIO = 0.6
# Fragments or link-residues below this size carry no reviewable claim;
# 16 chars keeps short but complete sentences (e.g. 8+ CJK characters).
MIN_PROSE_CHARS = 16
# Chunks whose characters are >= 60% links/URLs are link lists. Real prose
# chunks (~600 tokens) with a few inline links sit far below this.
MAX_LINK_DENSITY = 0.6


def strip_links(text: str) -> str:
    """Remove markdown links and bare URLs, keeping the surrounding prose."""
    stripped = _MD_LINK_RE.sub(" ", text)
    return _BARE_URL_RE.sub(" ", stripped)


def link_density(text: str) -> float:
    """Fraction of characters inside markdown links or bare URLs."""
    if not text:
        return 0.0
    linked = 0
    for match in _MD_LINK_RE.finditer(text):
        linked += match.end() - match.start()
    stripped = _MD_LINK_RE.sub(" ", text)
    for match in _BARE_URL_RE.finditer(stripped):
        linked += match.end() - match.start()
    return linked / len(text)


def prose_residue(text: str) -> int:
    """Non-whitespace characters remaining after links/URLs are stripped."""
    return len("".join(strip_links(text).split()))


def is_navigation_list(text: str) -> bool:
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < MIN_NAV_LINES:
        return False
    nav_lines = sum(1 for line in lines if _NAV_LINE_RE.match(line))
    return nav_lines / len(lines) >= NAV_LINE_RATIO


def is_junk_chunk(text: str) -> bool:
    """True when a chunk is boilerplate noise rather than reviewable prose."""
    stripped = (text or "").strip()
    if len(stripped) < MIN_PROSE_CHARS:
        return True
    if prose_residue(stripped) < MIN_PROSE_CHARS:
        return True  # link list: almost nothing outside the links
    if link_density(stripped) >= MAX_LINK_DENSITY:
        return True
    if is_navigation_list(stripped):
        return True
    if len(_BACKLINK_RE.findall(stripped)) >= MIN_BACKLINK_MARKERS:
        return True
    ref_lines = len(_REF_LINE_RE.findall(stripped))
    if ref_lines >= MIN_REF_LINES:
        return True
    # A lone reference-entry marker inside a tiny fragment is archive
    # residue ("Retrieved 15 March" surviving a page split).
    return len(stripped) < TINY_REF_FRAGMENT_CHARS and ref_lines >= 1
