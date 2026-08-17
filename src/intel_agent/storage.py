"""Atomic JSON/file I/O with SHA-256 integrity (port of storage.ts)."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path

from .models import CrawlSnapshot, IntelDocument, IntelError
from .security import source_group_of
from .source import source_type_for_domain

INTEL_ROOT = Path("data/intel")


def sha256(data: bytes | str) -> str:
    """SHA-256 hex digest; all content-addressed IDs and integrity checks use it."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def ensure_intel_dirs(cwd: Path) -> None:
    for rel in [
        "data/intel/tasks",
        "data/intel/documents",
        "data/intel/facts",
        "data/intel/evidence",
        "data/intel/reviews",
        "data/intel/coverage",
        "data/intel/crawls",
        "data/intel/materials",
        "data/raw",
        "output",
    ]:
        (cwd / rel).mkdir(parents=True, exist_ok=True)


def _safe_path(root: Path, path: str | Path) -> Path:
    """Resolve a path and reject any traversal outside `root`.

    The check is done on the fully-resolved path (symlinks included) so that
    `../escape` or a symlink pointing outside the workspace cannot smuggle
    reads/writes past the data boundary. This is the single guard every
    storage entry point relies on.
    """
    full = (root / path).resolve()
    if full != root.resolve() and root.resolve() not in full.parents:
        raise IntelError("INVALID_INPUT", f"路径越界: {path}")
    return full


def intel_path(cwd: Path, path: str | Path) -> Path:
    return _safe_path(cwd / INTEL_ROOT, path)


def workspace_path(cwd: Path, path: str | Path) -> Path:
    return _safe_path(cwd, path)


def read_json(cwd: Path, path: str) -> dict | list:
    """Read a JSON record from data/intel, raising STORAGE_CORRUPT on bad JSON."""
    full = intel_path(cwd, path)
    if not full.exists():
        raise IntelError("NOT_FOUND", f"记录不存在: {path}")
    try:
        return json.loads(full.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise IntelError("STORAGE_CORRUPT", f"JSON 损坏: {path}") from error


def read_json_object(cwd: Path, path: str) -> dict:
    value = read_json(cwd, path)
    if not isinstance(value, dict):
        raise IntelError("STORAGE_CORRUPT", f"JSON 对象格式错误: {path}")
    return value


def write_json_atomic(cwd: Path, path: str, value: object) -> None:
    # tmp -> os.replace guarantees the target is either the full new content or
    # the unchanged old content; a crash mid-write can never leave a truncated
    # record that would later fail (or worse, pass) integrity checks.
    ensure_intel_dirs(cwd)
    full = intel_path(cwd, path)
    full.parent.mkdir(parents=True, exist_ok=True)
    temporary = full.with_name(f"{full.name}.{uuid.uuid4()}.tmp")
    try:
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, full)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def write_file_atomic(cwd: Path, path: str, value: bytes | str) -> None:
    full = workspace_path(cwd, path)
    full.parent.mkdir(parents=True, exist_ok=True)
    temporary = full.with_name(f"{full.name}.{uuid.uuid4()}.tmp")
    try:
        data = value if isinstance(value, bytes) else value.encode("utf-8")
        temporary.write_bytes(data)
        os.replace(temporary, full)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def list_json(cwd: Path, directory: str) -> list[dict]:
    full = intel_path(cwd, directory)
    if not full.exists():
        return []
    return [
        read_json_object(cwd, f"{directory}/{name}")
        for name in sorted(os.listdir(full))
        if name.endswith(".json")
    ]


def save_crawl(cwd: Path, snapshot: CrawlSnapshot) -> None:
    """Atomically persist the resumable crawl frontier for one task."""
    write_json_atomic(
        cwd, f"crawls/{snapshot.task_id}.json", snapshot.model_dump()
    )


def load_crawl(cwd: Path, task_id: str) -> CrawlSnapshot:
    """Load one task's crawl frontier."""
    return CrawlSnapshot.model_validate(
        read_json(cwd, f"crawls/{task_id}.json")
    )


def list_crawls(cwd: Path) -> list[CrawlSnapshot]:
    """Load all crawl snapshots used for cross-task cache reuse."""
    return [
        CrawlSnapshot.model_validate(item) for item in list_json(cwd, "crawls")
    ]


def verify_document_integrity(cwd: Path, document: IntelDocument) -> None:
    """Re-derive every piece of a document record to prove it was not tampered.

    Files on disk must match the recorded SHA-256s (content tamper), the
    document ID must be reproducible from canonical_url + raw hash (metadata
    tamper), and source_group/source_type must still derive from the final URL
    (classification tamper). Any mismatch means the record or its files were
    modified outside the fetch pipeline.
    """
    raw_path = workspace_path(cwd, document.raw_path)
    text_path = workspace_path(cwd, document.text_path)
    if not raw_path.exists() or not text_path.exists():
        raise IntelError("DOCUMENT_TAMPERED", f"文档文件缺失: {document.id}")
    if sha256(raw_path.read_bytes()) != document.raw_sha256:
        raise IntelError("DOCUMENT_TAMPERED", f"原文哈希不匹配: {document.id}")
    if sha256(text_path.read_bytes()) != document.text_sha256:
        raise IntelError("DOCUMENT_TAMPERED", f"正文哈希不匹配: {document.id}")
    rendered_pair = (document.rendered_path, document.rendered_sha256)
    if document.collection_method == "browser" and not all(rendered_pair):
        raise IntelError(
            "DOCUMENT_TAMPERED", f"渲染文档元数据不匹配: {document.id}"
        )
    if document.collection_method == "http" and any(rendered_pair):
        raise IntelError(
            "DOCUMENT_TAMPERED", f"渲染文档元数据不匹配: {document.id}"
        )
    if all(rendered_pair):
        rendered_path = workspace_path(cwd, document.rendered_path or "")
        if not rendered_path.exists() or sha256(
            rendered_path.read_bytes()
        ) != document.rendered_sha256:
            raise IntelError(
                "DOCUMENT_TAMPERED", f"渲染正文哈希不匹配: {document.id}"
            )
    try:
        from urllib.parse import urlparse

        parsed = urlparse(document.final_url)
    except Exception as error:
        raise IntelError(
            "DOCUMENT_TAMPERED", f"文档元数据不匹配: {document.id}"
        ) from error
    identity = f"{document.canonical_url}\n{document.raw_sha256}"
    if document.collection_method == "browser":
        identity += f"\n{document.rendered_sha256}"
    if (
        document.id != f"doc-{sha256(identity)[:16]}"
        or document.source_group != source_group_of(document.final_url)
        or document.source_type
        != source_type_for_domain(parsed.hostname or "")
    ):
        raise IntelError(
            "DOCUMENT_TAMPERED", f"文档元数据不匹配: {document.id}"
        )
