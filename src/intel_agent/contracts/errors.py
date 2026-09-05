"""Domain error contract shared by every service boundary."""

from __future__ import annotations

from typing import Any

# Error codes required by spec §4.6. Each service may add narrower codes,
# but these stable values must cover the enumerated failure modes.
RETRYABLE_CODES = {
    "HTTP_ERROR",
    "TIMEOUT",
    "NETWORK_ERROR",
    "PROVIDER_UNAVAILABLE",
    "BACKEND_UNAVAILABLE",
    "RESOURCE_LIMIT",
    "BUDGET_EXHAUSTED",
}


class DomainError(Exception):
    """Error carrying a stable machine-readable code plus retry semantics.

    Raised by a public service when it cannot produce a valid result for a
    whole operation. Batch boundaries convert single-item DomainErrors into
    reports and preserve successful items (spec §4.6).
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        stage: str = "unknown",
        retryable: bool | None = None,
        retry_after_seconds: float | None = None,
        item_id: str | None = None,
        safe_details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.stage = stage
        self.retryable = (
            code in RETRYABLE_CODES if retryable is None else retryable
        )
        self.retry_after_seconds = retry_after_seconds
        self.item_id = item_id
        self.safe_details = safe_details or {}

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "stage": self.stage,
            "message": self.message,
            "retryable": self.retryable,
            "retry_after_seconds": self.retry_after_seconds,
            "item_id": self.item_id,
            "safe_details": self.safe_details,
        }
