"""Sanitized structured event logging (spec §13.2)."""

from __future__ import annotations

import json
import sys
from typing import Any, TextIO

# Header names whose values must never appear in ordinary logs.
_SECRET_HEADERS = {"authorization", "proxy-authorization", "cookie",
                   "set-cookie", "x-api-key", "api-key"}


def redact_secrets(value: Any, secrets: list[str] | None = None) -> Any:
    """Recursively replace secret substrings with '<redacted>'."""
    if isinstance(value, str):
        out = value
        for secret in secrets or []:
            if secret:
                out = out.replace(secret, "<redacted>")
        return out
    if isinstance(value, list):
        return [redact_secrets(v, secrets) for v in value]
    if isinstance(value, dict):
        return {
            k: "<redacted>" if k.lower() in _SECRET_HEADERS
            else redact_secrets(v, secrets)
            for k, v in value.items()
        }
    return value


class StructuredLogger:
    """Writes one JSON object per event to a sink (spec §13.2 fields)."""

    def __init__(self, sink: TextIO | None = None) -> None:
        self._sink = sink or sys.stderr
        self._secrets: list[str] = []

    def set_secrets(self, secrets: list[str]) -> None:
        self._secrets = [s for s in secrets if s]

    def event(self, **fields: Any) -> None:
        record = {
            k: redact_secrets(v, self._secrets) for k, v in fields.items()
        }
        print(json.dumps(record, ensure_ascii=False, default=str),
              file=self._sink)


DEFAULT_LOGGER = StructuredLogger()
