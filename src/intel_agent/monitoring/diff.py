"""Monitor change-detection helpers (spec 002 US2).

Identity strategy: a fact's key is derived from its *normalized* statement
(case/punctuation/whitespace folded away), so cosmetic rewording keeps the
same key. Statements whose keys differ but whose token overlap is high are
treated as wording drift (matched) or as a real value change (changed),
instead of collapsing everything into false ``new_fact`` events.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from contextlib import suppress
from difflib import SequenceMatcher
from urllib.parse import urlsplit

# Token-overlap band above which a key mismatch is wording drift only.
# Word-level ratios above ~0.85 are almost always the same fact restated;
# 0.8 (e.g. one value token swapped) is already a real value change.
MATCH_THRESHOLD = 0.85
# Band between MATCH and CHANGE threshold: same fact, changed value.
CHANGE_THRESHOLD = 0.6

_SPLIT_RE = re.compile(r"[^\w]+", re.UNICODE)


def normalize_statement(text: str) -> str:
    """Fold a statement to a stable token string (case, punctuation, width)."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    return " ".join(t for t in _SPLIT_RE.split(folded) if t)


def _tokens(text: str) -> list[str]:
    return normalize_statement(text).split()


def normalize_source_key(url: str) -> str:
    """Normalize a URL to page-level identity: lowercase host + path.

    Query strings and fragments carry tracking noise, not identity, so they
    are dropped; a trailing slash does not distinguish pages.
    """
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if not host:
        return ""
    with suppress(UnicodeError):  # hosts with underscores stay as-is
        host = host.encode("idna").decode("ascii")
    host = host.rstrip(".")
    path = parts.path or "/"
    if len(path) > 1:
        path = path.rstrip("/") or "/"
    return f"{host}{path}"


def derive_fact_key(subject: str, predicate: str, scope: dict) -> str:
    """Stable structured identity for a fact observation (no value)."""
    payload = {"subject": subject, "predicate": predicate, "scope": scope}
    canonical = str(sorted(payload.items()))
    return "fk-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


def _best_overlap(
    tokens: list[str],
    candidates: dict[str, list[str]],
    skip: set[str],
) -> tuple[str | None, float]:
    best_key, best_ratio = None, 0.0
    for key, other in candidates.items():
        if key in skip or not other:
            continue
        ratio = SequenceMatcher(None, tokens, other).ratio()
        if ratio > best_ratio:
            best_key, best_ratio = key, ratio
    return best_key, best_ratio


def diff_baseline(
    current: dict[str, str],
    baseline: dict[str, str],
    *,
    match_threshold: float = MATCH_THRESHOLD,
    change_threshold: float = CHANGE_THRESHOLD,
) -> tuple[set[str], set[str], set[str], set[str], dict[str, str]]:
    """Compare current fact statements (key -> statement) against a baseline.

    Returns ``(new_keys, changed_keys, matched_keys, removed_keys,
    near_matches)``. ``near_matches`` maps each changed current key to the
    baseline key it evolved from. Classification:

    - same key, normalized-equal statements -> matched
    - same key, normalized-different statements -> changed (new value)
    - key mismatch, overlap >= match_threshold -> wording drift, matched
    - change_threshold <= overlap < match_threshold -> changed value
    - overlap < change_threshold -> new fact
    - baseline keys never reached -> removed
    """
    baseline_tokens = {k: _tokens(v) for k, v in baseline.items()}
    new_keys: set[str] = set()
    changed_keys: set[str] = set()
    matched_keys: set[str] = set()
    removed_keys: set[str] = set()
    near_matches: dict[str, str] = {}
    consumed: set[str] = set()

    for key, statement in current.items():
        if key in baseline:
            if normalize_statement(statement) == normalize_statement(
                baseline[key]
            ):
                matched_keys.add(key)  # cosmetic drift keeps identity
            else:
                changed_keys.add(key)  # same identity, new value
                near_matches[key] = key
            consumed.add(key)
            continue
        best_key, ratio = _best_overlap(
            _tokens(statement), baseline_tokens, consumed
        )
        if best_key is not None and ratio >= match_threshold:
            matched_keys.add(key)
            consumed.add(best_key)
        elif best_key is not None and ratio >= change_threshold:
            changed_keys.add(key)
            near_matches[key] = best_key
            consumed.add(best_key)
        else:
            new_keys.add(key)

    removed_keys = set(baseline) - consumed
    return new_keys, changed_keys, matched_keys, removed_keys, near_matches
