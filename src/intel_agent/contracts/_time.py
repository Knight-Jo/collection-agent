"""Shared time/JSON helpers for contracts."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from pydantic import AwareDatetime as _AwareDatetime

type AwareDatetime = _AwareDatetime

type JsonValue = (
    str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]
)


def require_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("naive datetime is not allowed; use UTC")
    return value.astimezone(UTC)


def is_json_value(value: Any) -> bool:
    """True when value round-trips through strict JSON serialization."""
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError):
        return False
    return True
