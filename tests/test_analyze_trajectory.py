"""Structured trajectory analysis covers integrity and three projections."""

from __future__ import annotations

from scripts.analyze_trajectory import summarize, validate


def _event(
    sequence: int,
    event_type: str,
    payload: dict,
    *,
    event_id: str | None = None,
    parent_event_id: str | None = None,
    question_id: str | None = None,
    investigation_item_id: str | None = None,
) -> dict:
    return {
        "schema_version": "1.0",
        "run_id": "run-1",
        "task_id": "task-1",
        "event_id": event_id or f"event-{sequence}",
        "sequence": sequence,
        "parent_event_id": parent_event_id,
        "timestamp": f"2026-01-01T00:00:0{sequence}+00:00",
        "layer": "technical",
        "event_type": event_type,
        "origin": "system",
        "question_id": question_id,
        "investigation_item_id": investigation_item_id,
        "step_id": 1,
        "payload": payload,
    }


def test_validate_detects_missing_terminal_and_action_observation():
    events = [
        _event(1, "run_started", {}),
        _event(
            2,
            "action",
            {"action_id": "call-1", "tool": "web_search"},
        ),
    ]

    problems = validate(events)

    assert "run_finished 事件数量应为 1，实际为 0" in problems
    assert "action 无对应 observation: call-1" in problems


def test_summarize_projects_technical_business_and_result_metrics():
    events = [
        _event(1, "run_started", {}, event_id="start"),
        _event(
            2,
            "model_call",
            {
                "latency_ms": 120,
                "input_tokens": 100,
                "output_tokens": 20,
            },
        ),
        _event(
            3,
            "decision",
            {
                "reason_codes": ["LOW_COVERAGE"],
                "reason_source": "rule",
            },
            event_id="decision",
            question_id="question-1",
            investigation_item_id="item-1",
        ),
        _event(
            4,
            "action",
            {"action_id": "call-1", "tool": "web_search"},
            event_id="action",
            parent_event_id="decision",
            question_id="question-1",
            investigation_item_id="item-1",
        ),
        _event(
            5,
            "observation",
            {
                "action_id": "call-1",
                "status": "succeeded",
                "duration_ms": 50,
                "result": {"item_count": 4},
            },
            parent_event_id="action",
        ),
        _event(
            6,
            "state_updated",
            {
                "state_scope": "coverage",
                "before": {"gap_score": 5},
                "after": {"gap_score": 3},
                "delta": {"gap_score": {"before": 5, "after": 3}},
            },
        ),
        _event(
            7,
            "run_finished",
            {
                "status": "succeeded",
                "stage": "done",
                "requests": 1,
                "tool_calls": 1,
                "input_tokens": 100,
                "output_tokens": 20,
                "total_tokens": 120,
                "elapsed_ms": 6000,
                "final_coverage": {"gap_score": 3},
            },
        ),
    ]

    summary = summarize(events)

    assert summary["integrity"]["valid"] is True
    assert summary["technical"]["model_requests"] == 1
    assert summary["technical"]["tool_success_rate"] == 1.0
    assert summary["business"]["reason_codes"] == {"LOW_COVERAGE": 1}
    assert summary["business"]["attributed_actions"] == 1
    assert summary["business"]["coverage_gap_delta"] == -2
    assert summary["result"]["status"] == "succeeded"
    assert summary["resources"] == {
        "elapsed_seconds": 6.0,
        "input_tokens": 100,
        "output_tokens": 20,
        "model_requests": 1,
        "tool_calls": 1,
    }
