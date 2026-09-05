"""Canonical-JSON profile hashing."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def profile_id(config: Any) -> str:
    payload = json.dumps(
        config,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
