"""Web run materialization tests."""

import json
from datetime import UTC, datetime, timedelta

from intel_agent.materials import register_material
from intel_agent.task import create_task
from scripts.analyze_run import analyze
from scripts.web_run_to_experiment import materialize
from tests.conftest import DEFAULT_CRITERIA, make_document, save_evidence


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _seed_run(cwd, *, task, run_id: str, status: str, trace_events: list):
    """Insert a research_runs row and a trace.jsonl for one run."""
    from intel_agent.state_db import connect_state_db, initialize_state_db

    initialize_state_db(cwd)
    now = datetime.now(UTC)
    with connect_state_db(cwd) as connection:
        connection.execute(
            "INSERT INTO research_runs("
            "id, task_id, run_type, provenance, status, phase, outcome, "
            "created_at, started_at, completed_at, error, retry_of_run_id, "
            "trigger_message_id, input_committed_state_version, "
            "input_snapshot_json"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                task.id,
                "initial",
                "native",
                status,
                "collecting",
                "with_gaps" if status == "succeeded" else None,
                _iso(now),
                _iso(now),
                _iso(now + timedelta(seconds=80)),
                None,
                None,
                None,
                0,
                "{}",
            ),
        )
    trace_dir = cwd / "data" / "runs" / run_id
    trace_dir.mkdir(parents=True, exist_ok=True)
    if trace_events:
        (trace_dir / "trace.jsonl").write_text(
            "\n".join(json.dumps(e, ensure_ascii=False) for e in trace_events)
            + "\n",
            encoding="utf-8",
        )


def _trace_events(task_id: str, run_id: str) -> list[dict]:
    return [
        {
            "schema_version": "1.0",
            "run_id": run_id,
            "task_id": task_id,
            "event_type": "run_started",
            "layer": "evaluation",
            "sequence": 1,
            "payload": {"topic": "测试主题"},
        },
        {
            "schema_version": "1.0",
            "run_id": run_id,
            "task_id": task_id,
            "event_type": "action",
            "layer": "technical",
            "sequence": 2,
            "payload": {
                "action_id": "act-1",
                "tool": "web_search",
                "action_type": "web_search",
                "args": '{"query": "测试"}',
            },
        },
        {
            "schema_version": "1.0",
            "run_id": run_id,
            "task_id": task_id,
            "event_type": "observation",
            "layer": "technical",
            "sequence": 3,
            "payload": {
                "action_id": "act-1",
                "status": "succeeded",
                "result": {"ok": True, "candidate_count": 1},
            },
        },
        {
            "schema_version": "1.0",
            "run_id": run_id,
            "task_id": task_id,
            "event_type": "run_finished",
            "layer": "evaluation",
            "sequence": 4,
            "payload": {
                "stage": "done",
                "requests": 3,
                "tool_calls": 1,
                "input_tokens": 100,
                "output_tokens": 20,
                "total_tokens": 120,
                "final_coverage": {"gap_score": 5, "level": "insufficient"},
            },
        },
    ]


def test_materialize_succeeded_run_and_analyze(cwd, monkeypatch):
    task = create_task(
        cwd,
        "测试主题",
        ["问题甲", "问题乙"],
        DEFAULT_CRITERIA,
    )
    document = make_document(cwd, "关于测试主题的句子", "https://news.cn/x")
    register_material(
        cwd, task.id, document.final_url, document_id=document.id
    )
    from intel_agent.fact import save_fact

    fact = save_fact(cwd, task.id, task.questions[0].id, "测试主题事实")
    save_evidence(cwd, fact.id, document.id, "supports", "关于测试主题的句子")

    run_id = "run-test-0001"
    _seed_run(
        cwd,
        task=task,
        run_id=run_id,
        status="succeeded",
        trace_events=_trace_events(task.id, run_id),
    )
    monkeypatch.chdir(cwd)

    run_dir = materialize(cwd, run_id, "web-test", runs_dir=cwd / "runs")

    manifest = json.loads(
        (run_dir / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["web_run"] is True
    assert manifest["status"] == "succeeded"
    assert manifest["exit_code"] == 0
    assert manifest["elapsed_seconds"] == 80.0
    assert manifest["final_stage"] == "done"
    assert manifest["usage"]["tool_calls"] == 1
    assert manifest["topic"] == "测试主题"

    assert (run_dir / "trace.jsonl").exists()
    assert (run_dir / "state" / "intel.db").exists()
    assert (run_dir / "state" / "documents" / f"{document.id}.json").exists()
    assert (run_dir / "state" / "facts").exists()

    report = analyze(run_dir)
    assert "测试主题" in report
    assert "工具调用轨迹（共 1 次）" in report
    assert "web_search" in report
    assert "活跃事实: 1" in report


def test_materialize_failed_run_no_trace_is_tolerated(cwd, monkeypatch):
    task = create_task(cwd, "测试主题", ["问题甲", "问题乙"], DEFAULT_CRITERIA)
    run_id = "run-test-0002"
    _seed_run(
        cwd,
        task=task,
        run_id=run_id,
        status="failed",
        trace_events=[],
    )
    monkeypatch.chdir(cwd)

    run_dir = materialize(cwd, run_id, "web-failed", runs_dir=cwd / "runs")

    manifest = json.loads(
        (run_dir / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["status"] == "failed"
    assert manifest["exit_code"] == 1
    assert manifest.get("final_stage") is None
    assert not (run_dir / "trace.jsonl").exists()


def test_materialize_unknown_run_raises(cwd):
    create_task(cwd, "测试主题", ["问题甲", "问题乙"], DEFAULT_CRITERIA)
    with __import__("pytest").raises(ValueError):
        materialize(
            cwd, "run-does-not-exist", "web-missing", runs_dir=cwd / "runs"
        )
