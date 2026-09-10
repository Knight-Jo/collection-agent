"""Shared fixtures for new-core unit tests (T01/T02)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from intel_agent.storage.materials import MaterialStore
from intel_agent.storage.resources import ResourceStore
from intel_agent.storage.tasks import TaskStore


@pytest.fixture
def material_store(tmp_path: Path) -> Iterator[MaterialStore]:
    store = MaterialStore(tmp_path / "research.sqlite")
    yield store
    store.close()


@pytest.fixture
def task_store(material_store: MaterialStore) -> TaskStore:
    return TaskStore(material_store.db)


@pytest.fixture
def import_root(tmp_path: Path) -> Path:
    root = tmp_path / "imports"
    root.mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture
def resource_store(
    material_store: MaterialStore, import_root: Path, tmp_path: Path
) -> ResourceStore:
    return ResourceStore(
        root=tmp_path / "resources",
        allowed_import_roots=[import_root],
        store=material_store,
    )
