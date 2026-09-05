"""MaterialStore identity and transaction tests (T02)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from intel_agent.contracts.errors import DomainError


def test_same_bytes_share_revision_but_not_document(
    material_store, resource_store, import_root
):
    path = import_root / "input.txt"
    path.write_text("研究材料", encoding="utf-8")
    resource = asyncio.run(resource_store.import_file(path))
    left = material_store.resolve_identity("https://example.org/a")
    right = material_store.resolve_identity("https://example.org/b")
    rev = material_store.resolve_revision(
        left.document_id, resource.resource_id
    )
    assert rev == material_store.resolve_revision(
        left.document_id, resource.resource_id
    )
    assert left.document_id != right.document_id


def test_resolve_identity_is_stable_and_idempotent(material_store):
    first = material_store.resolve_identity("https://example.org/a")
    second = material_store.resolve_identity("https://example.org/a")
    assert first.document_id == second.document_id


def test_import_outside_roots_is_rejected(resource_store, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    with pytest.raises(DomainError) as raised:
        asyncio.run(resource_store.import_file(outside))
    assert raised.value.code == "INVALID_REQUEST"


def test_resource_round_trip(resource_store, import_root):
    path = import_root / "doc.txt"
    path.write_text("hello world", encoding="utf-8")
    resource = asyncio.run(resource_store.import_file(path))
    assert resource.byte_length == len("hello world".encode())
    with resource_store.open(resource.resource_id) as fh:
        assert fh.read().decode("utf-8") == "hello world"


def test_import_symlink_escape_rejected(resource_store, tmp_path, import_root):
    target = tmp_path / "secret.txt"
    target.write_text("secret", encoding="utf-8")
    link = import_root / "link.txt"
    link.symlink_to(target)
    with pytest.raises(DomainError):
        asyncio.run(resource_store.import_file(link))


def test_missing_resource_raises(material_store):
    with pytest.raises(DomainError) as raised:
        material_store.get_resource("res-does-not-exist")
    assert raised.value.code == "NOT_FOUND"
