"""Deterministic identity helpers (reproducible revision/artifact IDs)."""

from __future__ import annotations

import hashlib
import uuid


def sha256(data: str | bytes) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4()}"


def document_id(source_key: str) -> str:
    return f"doc-{sha256(source_key)[:24]}"


def revision_id(document_id: str, content_hash: str) -> str:
    return f"rev-{sha256(document_id + '\n' + content_hash)[:24]}"


def artifact_id(*parts: str) -> str:
    return f"art-{sha256('\n'.join(parts))[:24]}"
