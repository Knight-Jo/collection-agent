"""Tests for structured trajectory recording and deterministic reason attribution."""

from __future__ import annotations

import json
import threading

from intel_agent import trajectory
from intel_agent.models import SufficiencyCriteria
from intel_agent.reason_rules import derive_reason_codes, reason_summary
from intel_agent.task import create_task, record_search_attempt
from intel_agent.trajectory import (
    DecisionPayload,
    JsonlTrajectoryRecorder,
    canonical_hash,
    emit,
    emit_state_updated,
    make_event,
)


def _records(path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_recorder_stamps_envelope(tmp_path):
    out = tmp_path / "trace.jsonl"
    recorder = JsonlTrajectoryRecorder(out)
    trajectory.bind_run("run-1")
    trajectory.set_recorder(recorder)
    trajectory.set_task_id("task-1")
    trajectory.set_step_id(1)
    event_id = emit(
        make_event(
            "decision",
            "model",
            DecisionPayload(
                decision="web_search",
                reason_codes=["LOW_COVERAGE"],
                reason_source="derived",
            ),
        )
    )
    recorder.close()
    envelope = _records(out)[0]
    assert envelope["schema_version"] == "1.0"
    assert envelope["run_id"] == "run-1"
    assert envelope["task_id"] == "task-1"
    assert envelope["event_id"] == event_id
    assert envelope["sequence"] == 1
    assert envelope["step_id"] == 1
    assert envelope["event_type"] == "decision"
    assert envelope["origin"] == "model"
    assert envelope["payload"]["reason_source"] == "derived"


def test_sequence_monotonic(tmp_path):
    out = tmp_path / "trace.jsonl"
    recorder = JsonlTrajectoryRecorder(out)
    trajectory.bind_run("run-1")
    trajectory.set_recorder(recorder)
    for _ in range(5):
        emit(make_event("action", "model", {}, layer="technical"))
    recorder.close()
    assert [r["sequence"] for r in _records(out)] == [1, 2, 3, 4, 5]


def test_recorder_record_is_thread_safe(tmp_path):
    out = tmp_path / "trace.jsonl"
    recorder = JsonlTrajectoryRecorder(out)
    trajectory.bind_run("run-1")
    trajectory.set_task_id("task-1")
    event = make_event("action", "model", {}, layer="technical")

    def worker():
        for _ in range(100):
            recorder.record(event)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    recorder.close()

    sequences = [r["sequence"] for r in _records(out)]
    assert sequences == list(range(1, 401))


def test_emit_is_noop_without_recorder():
    assert emit(make_event("action", "model", {})) is None
    assert emit_state_updated("task", "t", {"a": 1}, {"a": 2}) is None


def test_state_updated_version_and_hash(tmp_path):
    out = tmp_path / "trace.jsonl"
    recorder = JsonlTrajectoryRecorder(out)
    trajectory.bind_run("run-1")
    trajectory.set_recorder(recorder)
    emit_state_updated("task", "task-1", {"a": 1}, {"a": 2})
    emit_state_updated("task", "task-1", {"a": 2}, {"a": 3})
    recorder.close()
    records = [r for r in _records(out) if r["event_type"] == "state_updated"]
    assert records[0]["payload"]["version_before"] == 0
    assert records[0]["payload"]["version_after"] == 1
    assert records[1]["payload"]["version_before"] == 1
    assert records[1]["payload"]["version_after"] == 2
    assert records[0]["payload"]["delta"] == {"a": {"before": 1, "after": 2}}
    assert records[0]["payload"]["hash_after"] == canonical_hash({"a": 2})


def test_canonical_hash_key_order_independent():
    assert canonical_hash({"a": 1, "b": 2}) == canonical_hash({"b": 2, "a": 1})


def test_derive_reason_codes():
    assert derive_reason_codes("web_fetch", {}) == [
        "SOURCE_CONTENT_NOT_ACQUIRED"
    ]
    assert derive_reason_codes("web_search", {"gap_score": 3}) == [
        "LOW_COVERAGE"
    ]
    assert derive_reason_codes("web_search", {"gap_score": 0}) == [
        "SEARCH_RESULT_NOT_MATERIALIZED"
    ]
    assert derive_reason_codes("evidence_audit", {}) == [
        "EVIDENCE_NOT_VERIFIED"
    ]
    assert derive_reason_codes("fact_save", {}) == ["CLAIM_NOT_VERIFIED"]
    assert derive_reason_codes("generate_research_report", {}) == []


def test_reason_summary():
    assert reason_summary(["LOW_COVERAGE"]) == "关键问题覆盖不足"
    assert reason_summary([]) == ""


def test_state_coemit_from_record_search_attempt(cwd):
    out = cwd / "trace.jsonl"
    recorder = JsonlTrajectoryRecorder(out)
    trajectory.bind_run("run-1")
    trajectory.set_recorder(recorder)
    task = create_task(
        cwd, "主题", ["问题一", "问题二"], SufficiencyCriteria()
    )
    before = task.collection.search_attempts
    record_search_attempt(cwd, task.id)
    recorder.close()
    records = [r for r in _records(out) if r["event_type"] == "state_updated"]
    assert len(records) == 1
    payload = records[0]["payload"]
    assert payload["state_scope"] == "task"
    assert payload["state_id"] == task.id
    assert payload["after"]["search_attempts"] == before + 1
