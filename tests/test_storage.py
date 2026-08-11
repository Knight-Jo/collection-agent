"""Atomic storage failure regressions."""

import pytest

import intel_agent.storage as storage_module
from intel_agent.storage import read_json_object, write_json_atomic


def test_atomic_json_replace_failure_preserves_previous_record(
    cwd, monkeypatch
):
    write_json_atomic(cwd, "crawls/task-1.json", {"status": "old"})

    def fail_replace(_source, _target):
        raise OSError("replace failed")

    monkeypatch.setattr(storage_module.os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        write_json_atomic(cwd, "crawls/task-1.json", {"status": "new"})

    assert read_json_object(cwd, "crawls/task-1.json") == {"status": "old"}
    assert list((cwd / "data/intel/crawls").glob("*.tmp")) == []
