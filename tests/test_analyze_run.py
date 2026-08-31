"""Current-state compatibility tests for scripts/analyze_run.py."""

import json

from intel_agent.task import create_task, save_task
from scripts.analyze_run import _evidence_funnel, analyze
from tests.conftest import DEFAULT_CRITERIA


def test_analyze_reads_final_task_from_current_sqlite_state(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    task = create_task(
        run_dir,
        "测试主题",
        ["问题甲", "问题乙"],
        DEFAULT_CRITERIA,
    )
    save_task(
        run_dir,
        task.model_copy(
            update={"stage": "done", "completion_status": "with_gaps"}
        ),
    )

    report = analyze(run_dir)

    assert "stage: done" in report
    assert "completion_status: with_gaps" in report
    assert "report=False" in report


def test_evidence_funnel_counts_all_current_search_tools(tmp_path):
    calls = [
        {"tool": tool, "args": {}}
        for tool in (
            "web_search",
            "github_search",
            "academic_search",
            "news_search",
            "academic",
            "software",
            "news",
        )
    ]

    funnel = _evidence_funnel(tmp_path, calls)

    assert funnel is not None
    assert funnel["searches"] == 7


def test_analyze_keeps_valid_events_from_interrupted_trace(tmp_path):
    (tmp_path / "trace.jsonl").write_text(
        json.dumps(
            {
                "event_type": "action",
                "payload": {
                    "tool": "web_search",
                    "action_id": "call-1",
                    "args": {"query": "测试"},
                },
            }
        )
        + "\n{interrupted",
        encoding="utf-8",
    )

    report = analyze(tmp_path)

    assert "工具调用轨迹（共 1 次）" in report
