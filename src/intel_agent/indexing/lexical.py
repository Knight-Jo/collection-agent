"""Chinese-aware lexical tokenization (spec §10.2)."""

from __future__ import annotations

import re

_CJK = re.compile(r"[\u4e00-\u9fff]+")
_WORD = re.compile(r"[a-z0-9]+", re.IGNORECASE)


def lexical_tokens(text: str) -> list[str]:
    """ASCII-prefixed unigrams/bigrams for CJK and words for Latin text.

    Prefixes keep term types distinct and avoid any downstream tokenizer
    re-splitting CJK into unsearchable units.
    """
    tokens: list[str] = []
    for match in _CJK.finditer(text):
        run = match.group()
        tokens.extend(f"u:{ch}" for ch in run)
        tokens.extend(f"b:{run[i]}{run[i + 1]}" for i in range(len(run) - 1))
    for match in _WORD.finditer(text):
        tokens.append(f"w:{match.group().lower()}")
    return tokens
