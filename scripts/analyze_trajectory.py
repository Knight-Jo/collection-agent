"""Reconstruct a decision's full causal chain from a trajectory JSONL.

用法:
  python scripts/analyze_trajectory.py <trace.jsonl> --action 17
  python scripts/analyze_trajectory.py <trace.jsonl> --action-id <id>
  python scripts/analyze_trajectory.py <trace.jsonl> --check

For a selected ``action_id`` it rebuilds, from the single event stream:

    Task/Run -> Question -> State before -> Decision(+source) -> Action
              -> Observation -> subsequent State changes

``--check`` validates the stream invariants (strictly increasing ``sequence``,
no orphan ``parent_event_id``, every ``observation`` resolves to an ``action``).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from math import ceil
from pathlib import Path


def load_events(path: Path) -> list[dict]:
    events: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        events.append(json.loads(line))
    return events


def action_by_id(events: list[dict], action_id: str) -> dict | None:
    for event in events:
        if (
            event["event_type"] == "action"
            and event["payload"].get("action_id") == action_id
        ):
            return event
    return None


def by_id(events: list[dict], event_id: str | None) -> dict | None:
    if event_id is None:
        return None
    for event in events:
        if event["event_id"] == event_id:
            return event
    return None


def reconstruct(events: list[dict], action_id: str) -> dict:
    action = action_by_id(events, action_id)
    if action is None:
        raise SystemExit(f"未找到 action_id={action_id} 的 action 事件")
    decision = by_id(events, action.get("parent_event_id"))
    observation = next(
        (
            e
            for e in events
            if e["event_type"] == "observation"
            and e["payload"].get("action_id") == action_id
        ),
        None,
    )
    step_id = action.get("step_id")
    state_changes = [
        e["payload"]
        for e in events
        if e["event_type"] == "state_updated"
        and e.get("step_id") == step_id
        and e["sequence"] >= action["sequence"]
    ]
    return {
        "run_id": action.get("run_id"),
        "task_id": action.get("task_id"),
        "step_id": step_id,
        "question_id": action.get("question_id"),
        "state_before": (decision or {})
        .get("payload", {})
        .get("state_snapshot", {}),
        "decision": decision,
        "action": action,
        "observation": observation,
        "state_changes": state_changes,
    }


def validate(events: list[dict]) -> list[str]:
    """Return integrity problems without mutating the trajectory."""
    problems: list[str] = []
    ids = {
        event.get("event_id")
        for event in events
        if event.get("event_id") is not None
    }
    if len(ids) != len(events):
        problems.append("event_id 缺失或重复")
    prev_sequence = -1
    for event in events:
        if event.get("schema_version") != "1.0":
            problems.append(
                f"不支持的 schema_version: {event.get('schema_version')}"
            )
        sequence = event.get("sequence")
        if not isinstance(sequence, int):
            problems.append("sequence 缺失或不是整数")
            continue
        if sequence <= prev_sequence:
            problems.append(
                f"sequence 非严格递增: {sequence} 在 {prev_sequence} 之后"
            )
        prev_sequence = sequence
        parent = event.get("parent_event_id")
        if parent is not None and parent not in ids:
            problems.append(f"孤儿 parent_event_id: {parent}")
    action_ids = {
        event.get("payload", {}).get("action_id")
        for event in events
        if event.get("event_type") == "action"
        and event.get("payload", {}).get("action_id") is not None
    }
    observation_ids = {
        event.get("payload", {}).get("action_id")
        for event in events
        if event.get("event_type") == "observation"
        and event.get("payload", {}).get("action_id") is not None
    }
    for event in events:
        if event.get("event_type") == "observation":
            action_id = event.get("payload", {}).get("action_id")
            if action_id not in action_ids:
                problems.append(f"observation 无对应 action: {action_id}")
    for action_id in sorted(action_ids - observation_ids):
        problems.append(f"action 无对应 observation: {action_id}")
    for event_type in ("run_started", "run_finished"):
        count = sum(event.get("event_type") == event_type for event in events)
        if count != 1:
            problems.append(f"{event_type} 事件数量应为 1，实际为 {count}")
    return problems


def check(events: list[dict]) -> int:
    problems = validate(events)
    if problems:
        for problem in problems:
            print(f"FAIL: {problem}")
        return 1
    print(
        f"OK: {len(events)} 事件，sequence 单调，无孤儿引用，observation 全部可解析"
    )
    return 0


def _percentile(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, ceil(len(ordered) * percentile) - 1)]


def _elapsed_seconds(events: list[dict], terminal: dict) -> float | None:
    elapsed_ms = terminal.get("payload", {}).get("elapsed_ms")
    if isinstance(elapsed_ms, (int, float)):
        return round(elapsed_ms / 1000, 3)
    try:
        started = datetime.fromisoformat(events[0]["timestamp"])
        finished = datetime.fromisoformat(events[-1]["timestamp"])
    except (KeyError, TypeError, ValueError, IndexError):
        return None
    return round(max(0.0, (finished - started).total_seconds()), 3)


def summarize(events: list[dict]) -> dict:
    """Build deterministic L1/L2/L3 projections from one event stream."""
    terminal = next(
        (
            event
            for event in reversed(events)
            if event.get("event_type") == "run_finished"
        ),
        {},
    )
    terminal_payload = terminal.get("payload", {})
    model_calls = [
        event for event in events if event.get("event_type") == "model_call"
    ]
    decisions = [
        event for event in events if event.get("event_type") == "decision"
    ]
    actions = [
        event for event in events if event.get("event_type") == "action"
    ]
    observations = [
        event for event in events if event.get("event_type") == "observation"
    ]
    state_updates = [
        event for event in events if event.get("event_type") == "state_updated"
    ]
    latencies = [
        int(value)
        for event in model_calls
        if isinstance(
            (value := event.get("payload", {}).get("latency_ms")),
            (int, float),
        )
    ]
    tool_latencies = [
        int(value)
        for event in observations
        if isinstance(
            (value := event.get("payload", {}).get("duration_ms")),
            (int, float),
        )
    ]
    tool_counts = Counter(
        str(event.get("payload", {}).get("tool", "unknown"))
        for event in actions
    )
    statuses = Counter(
        (
            "failed"
            if event.get("payload", {}).get("result", {}).get("ok") is False
            else str(event.get("payload", {}).get("status", "unknown"))
        )
        for event in observations
    )
    reason_codes = Counter(
        str(code)
        for event in decisions
        for code in event.get("payload", {}).get("reason_codes", [])
    )
    reason_sources = Counter(
        str(event.get("payload", {}).get("reason_source", "unknown"))
        for event in decisions
    )
    attributed = sum(
        bool(event.get("question_id") or event.get("investigation_item_id"))
        for event in actions
    )
    actions_by_question = Counter(
        str(event["question_id"])
        for event in actions
        if event.get("question_id")
    )
    actions_by_item = Counter(
        str(event["investigation_item_id"])
        for event in actions
        if event.get("investigation_item_id")
    )
    coverage_updates = [
        event
        for event in state_updates
        if event.get("payload", {}).get("state_scope") == "coverage"
    ]
    first_gap = None
    last_gap = None
    if coverage_updates:
        first = coverage_updates[0].get("payload", {})
        last = coverage_updates[-1].get("payload", {})
        first_gap = first.get("before", {}).get("gap_score")
        if first_gap is None:
            first_gap = first.get("after", {}).get("gap_score")
        last_gap = last.get("after", {}).get("gap_score")
    gap_delta = (
        last_gap - first_gap
        if isinstance(first_gap, (int, float))
        and isinstance(last_gap, (int, float))
        else None
    )
    successful = statuses.get("succeeded", 0)
    elapsed_seconds = _elapsed_seconds(events, terminal)
    resources = {
        "elapsed_seconds": elapsed_seconds,
        "input_tokens": terminal_payload.get(
            "input_tokens",
            sum(
                event.get("payload", {}).get("input_tokens") or 0
                for event in model_calls
            ),
        ),
        "output_tokens": terminal_payload.get(
            "output_tokens",
            sum(
                event.get("payload", {}).get("output_tokens") or 0
                for event in model_calls
            ),
        ),
        "model_requests": terminal_payload.get("requests", len(model_calls)),
        "tool_calls": terminal_payload.get("tool_calls", len(actions)),
    }
    problems = validate(events)
    return {
        "schema_version": "1.0",
        "run_id": next(
            (event.get("run_id") for event in events if event.get("run_id")),
            None,
        ),
        "task_id": next(
            (
                event.get("task_id")
                for event in reversed(events)
                if event.get("task_id")
            ),
            None,
        ),
        "integrity": {"valid": not problems, "problems": problems},
        "technical": {
            "model_requests": resources["model_requests"],
            "input_tokens": resources["input_tokens"],
            "output_tokens": resources["output_tokens"],
            "decision_cycle_latency_p50_ms": _percentile(latencies, 0.5),
            "decision_cycle_latency_p95_ms": _percentile(latencies, 0.95),
            "tool_calls": resources["tool_calls"],
            "tool_counts": dict(tool_counts),
            "tool_results": len(observations),
            "tool_statuses": dict(statuses),
            "tool_success_rate": (
                round(successful / len(observations), 4)
                if observations
                else None
            ),
            "tool_latency_p50_ms": _percentile(tool_latencies, 0.5),
            "tool_latency_p95_ms": _percentile(tool_latencies, 0.95),
        },
        "business": {
            "decisions": len(decisions),
            "reason_codes": dict(reason_codes),
            "reason_sources": dict(reason_sources),
            "attributed_actions": attributed,
            "unattributed_actions": len(actions) - attributed,
            "actions_by_question": dict(actions_by_question),
            "actions_by_investigation_item": dict(actions_by_item),
            "fact_updates": sum(
                event.get("payload", {}).get("state_scope") == "fact"
                for event in state_updates
            ),
            "evidence_updates": sum(
                event.get("payload", {}).get("state_scope") == "evidence"
                for event in state_updates
            ),
            "coverage_gap_delta": gap_delta,
        },
        "result": {
            "status": terminal_payload.get("status", "unknown"),
            "stage": terminal_payload.get("stage", ""),
            "error_code": terminal_payload.get("error_code"),
            "final_coverage": terminal_payload.get("final_coverage", {}),
        },
        "resources": resources,
    }


def _fmt(event: dict | None) -> str:
    if event is None:
        return "  (缺失)"
    payload = event.get("payload", {})
    return (
        f"  [{event['event_type']}] {json.dumps(payload, ensure_ascii=False)}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("trace", help="trace.jsonl 路径")
    parser.add_argument("--action", type=int, help="第 N 次 web_search 的序号")
    parser.add_argument("--action-id", help="按 action_id 精确重建")
    parser.add_argument("--check", action="store_true", help="校验不变量")
    parser.add_argument(
        "--summary", action="store_true", help="输出 L1/L2/L3 JSON 摘要"
    )
    parser.add_argument("--output", type=Path, help="将摘要写入 JSON 文件")
    args = parser.parse_args()

    path = Path(args.trace)
    if not path.exists():
        print(f"文件不存在: {path}", file=sys.stderr)
        return 1
    events = load_events(path)
    if not events:
        print("空轨迹", file=sys.stderr)
        return 1

    if args.check:
        return check(events)

    if args.summary or (args.action is None and args.action_id is None):
        rendered = json.dumps(summarize(events), ensure_ascii=False, indent=2)
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered + "\n", encoding="utf-8")
        else:
            print(rendered)
        return 0

    if args.action is not None:
        searches = [
            e["payload"]["action_id"]
            for e in events
            if e["event_type"] == "action"
            and e["payload"].get("tool") == "web_search"
        ]
        if args.action < 1 or args.action > len(searches):
            print(
                f"序号越界: 共 {len(searches)} 次 web_search", file=sys.stderr
            )
            return 1
        action_id = searches[args.action - 1]
    elif args.action_id:
        action_id = args.action_id
    else:
        raise AssertionError("unreachable")

    chain = reconstruct(events, action_id)
    action = chain["action"]
    print(
        f"Run {chain['run_id']} / Task {chain['task_id']} / "
        f"Step {chain['step_id']} / Question {chain['question_id']}"
    )
    print("前置状态:", json.dumps(chain["state_before"], ensure_ascii=False))
    decision = chain["decision"]
    if decision is None:
        print("决策: (缺失)")
    else:
        payload = decision["payload"]
        print(
            f"决策: {payload.get('decision')} "
            f"reason_codes={payload.get('reason_codes')} "
            f"reason_source={payload.get('reason_source')}"
        )
    print("行动:", _fmt(action))
    print("观察:", _fmt(chain["observation"]))
    if chain["state_changes"]:
        print("后续状态变化:")
        for change in chain["state_changes"]:
            print("  ", json.dumps(change, ensure_ascii=False))
    else:
        print("后续状态变化: (无)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
