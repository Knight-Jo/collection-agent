"""Content-addressed resource byte storage (spec §7.3, §9.2)."""

from __future__ import annotations

import hashlib
import os
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

from ..contracts.errors import DomainError
from ..contracts.resources import Resource, ResourceOrigin
from ._ids import new_id, sha256

CHUNK_SIZE = 64 * 1024


class ResourceStore:
    """Stores immutable resource bytes, content-addressed by SHA-256.

    Bytes live on disk under ``root``; the database (via MaterialStore) holds
    the metadata. Distinct origins may share one blob when their content hash
    matches, but each keeps its own resource record.
    """

    def __init__(
        self,
        root: Path,
        allowed_import_roots: list[Path],
        store,
    ) -> None:
        self.root = root
        self.allowed_import_roots = [p.resolve() for p in allowed_import_roots]
        self.store = store
        self.root.mkdir(parents=True, exist_ok=True)

    def _blob_path(self, content_hash: str) -> Path:
        return self.root / content_hash[:2] / content_hash

    def _validate_import_path(self, path: Path) -> Path:
        resolved = path.resolve()
        if not any(resolved == root or root in resolved.parents
                   for root in self.allowed_import_roots):
            raise DomainError(
                "INVALID_REQUEST",
                f"import path outside allowed roots: {path}",
                stage="import",
            )
        return resolved

    async def import_file(self, path: str | Path) -> Resource:
        resolved = self._validate_import_path(Path(path))
        if not resolved.is_file():
            raise DomainError(
                "NOT_FOUND", f"not a file: {resolved}", stage="import"
            )
        with resolved.open("rb") as fh:
            return await self.write_stream(
                self._iter_file(fh),
                origin=ResourceOrigin(
                    local_display_name=resolved.name,
                    acquired_at=datetime.now(UTC),
                ),
                media_type=_guess_media_type(resolved),
                max_bytes=None,
            )

    @staticmethod
    async def _iter_file(fh: BinaryIO) -> AsyncIterator[bytes]:
        while chunk := fh.read(CHUNK_SIZE):
            yield chunk

    async def write_stream(
        self,
        chunks,
        *,
        origin: ResourceOrigin,
        media_type: str,
        max_bytes: int | None = None,
        parent_resource_id: str | None = None,
        transform=None,
    ) -> Resource:
        digest = hashlib.sha256()
        total = 0
        tmp = self.root / f".tmp-{new_id('blob')}"
        try:
            with tmp.open("wb") as out:
                async for chunk in chunks:
                    data = bytes(chunk)
                    total += len(data)
                    if max_bytes is not None and total > max_bytes:
                        raise DomainError(
                            "TOO_LARGE",
                            f"resource exceeds {max_bytes} bytes",
                            stage="fetch",
                        )
                    digest.update(data)
                    out.write(data)
                out.flush()
                os.fsync(out.fileno())
            content_hash = digest.hexdigest()
            blob = self._blob_path(content_hash)
            if not blob.exists():
                blob.parent.mkdir(parents=True, exist_ok=True)
                os.replace(tmp, blob)
            else:
                tmp.unlink(missing_ok=True)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
        return self._make_resource(
            content_hash=content_hash,
            byte_length=total,
            media_type=media_type,
            origin=origin,
            parent_resource_id=parent_resource_id,
            transform=transform,
        )

    def _make_resource(
        self,
        *,
        content_hash: str,
        byte_length: int,
        media_type: str,
        origin: ResourceOrigin,
        parent_resource_id: str | None,
        transform,
    ) -> Resource:
        resource = Resource(
            resource_id=new_id("res"),
            content_hash=content_hash,
            byte_length=byte_length,
            media_type=media_type,
            content_ref=f"{content_hash[:2]}/{content_hash}",
            origin=origin,
            created_at=datetime.now(UTC),
            parent_resource_id=parent_resource_id,
            transform=transform,
        )
        self.store.register_resource(resource)
        return resource

    @contextmanager
    def open(self, resource_id: str) -> Iterator[BinaryIO]:
        resource = self.store.get_resource(resource_id)
        path = self._blob_path(resource.content_hash)
        if not path.exists():
            raise DomainError(
                "NOT_FOUND", f"blob missing: {resource_id}", stage="storage"
            )
        fh = path.open("rb")
        try:
            yield fh
        finally:
            fh.close()

    def blob_path(self, resource_id: str) -> Path:
        """Filesystem path to the content-addressed blob.

        Intended only for subprocess-based backends (ffmpeg) that require a
        real path; never exposed over the HTTP surface.
        """
        resource = self.store.get_resource(resource_id)
        path = self._blob_path(resource.content_hash)
        if not path.exists():
            raise DomainError(
                "NOT_FOUND", f"blob missing: {resource_id}", stage="storage"
            )
        return path


def _guess_media_type(path: Path) -> str:
    from mimetypes import guess_type

    return guess_type(path.name)[0] or "application/octet-stream"
