"""Resource and fetch-result contracts (spec §4.2)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from ._time import AwareDatetime, JsonValue, require_aware


class FetchRequest(BaseModel):
    """A single acquisition target (spec §4.2, §3.4 allow_media)."""

    url: str
    mode: Literal["auto", "http", "browser"] = "auto"
    headers: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: float = Field(default=30.0, gt=0)
    max_bytes: int | None = Field(default=None, gt=0)
    # Explicit media-download permission (spec §14): only after MIME/signature
    # validation may the larger 1 GiB media limit replace the 50 MiB default.
    allow_media: bool = False
    # Conditional-request validators: sent as If-None-Match / If-Modified-
    # Since when present, letting servers answer 304 instead of a full body.
    etag: str | None = None
    last_modified: str | None = None


class ResourceOrigin(BaseModel):
    requested_url: str | None = None
    final_url: str | None = None
    local_display_name: str | None = None
    acquired_at: AwareDatetime

    @field_validator("acquired_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        return require_aware(value)


class Resource(BaseModel):
    """An immutable byte resource; content_ref is an opaque store handle."""

    resource_id: str
    content_hash: str
    byte_length: int = Field(ge=0)
    media_type: str
    content_ref: str
    origin: ResourceOrigin
    created_at: AwareDatetime
    parent_resource_id: str | None = None
    transform: JsonValue | None = None

    @field_validator("created_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        return require_aware(value)


class FetchResult(BaseModel):
    # ``resource`` is None exactly when the server answered 304 to a
    # conditional request: nothing was downloaded, so nothing was stored.
    resource: Resource | None = None
    status_code: int | None = None
    not_modified: bool = False
    etag: str | None = None
    last_modified: str | None = None
    safe_headers: dict[str, str] = Field(default_factory=dict)
    method: Literal["http", "browser"] = "http"
    elapsed_ms: int = Field(ge=0)
    warnings: list[str] = Field(default_factory=list)
