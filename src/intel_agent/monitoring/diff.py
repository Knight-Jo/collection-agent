"""Monitor change-detection helpers (spec 002 US2)."""

from __future__ import annotations

import hashlib
from urllib.parse import urlsplit


def normalize_source_key(url: str) -> str:
    """Normalize a URL to a site hostname (lowercase, IDNA, no trailing dot)."""
    host = (urlsplit(url).hostname or "").lower()
    host = host.encode("idna").decode("ascii") if host else host
    return host.rstrip(".")


def derive_fact_key(subject: str, predicate: str, scope: dict) -> str:
    """Stable structured identity for a fact observation (no value)."""
    payload = {"subject": subject, "predicate": predicate, "scope": scope}
    canonical = str(sorted(payload.items()))
    return "fk-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


def diff_baseline(
    current: dict[str, str], baseline: dict[str, str]
) -> tuple[set[str], set[str], set[str]]:
    """Compare current fact statements (key -> statement) against a baseline.

    Returns (new_keys, changed_keys, matched_keys). Text rewriting alone does
    not imply change: identity is the normalized key; a value change is only a
    change when the key matches but the statement differs.
    """
    new_keys = set(current) - set(baseline)
    changed_keys = {
        k
        for k in current.keys() & baseline.keys()
        if current[k] != baseline[k]
    }
    matched_keys = {
        k
        for k in current.keys() & baseline.keys()
        if current[k] == baseline[k]
    }
    return new_keys, changed_keys, matched_keys
