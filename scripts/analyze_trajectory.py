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
from pathlib import Path


def load_events(path: Path) -> list[dict]:
    events: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        events.append(json.loads(line))
    return events


def build_index(events: list[dict]) -> dict[str, list[dict]]:
    index: dict[str, list[dict]] = {}
    for event in events:
        index.setdefault(event["event_type"], []).append(event)
    return index


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


def check(events: list[dict]) -> int:
    problems: list[str] = []
    ids = {e["event_id"] for e in events}
    prev_sequence = -1
    for event in events:
        sequence = event["sequence"]
        if sequence <= prev_sequence:
            problems.append(
                f"sequence 非严格递增: {sequence} 在 {prev_sequence} 之后"
            )
        prev_sequence = sequence
        parent = event.get("parent_event_id")
        if parent is not None and parent not in ids:
            problems.append(f"孤儿 parent_event_id: {parent}")
    action_ids = {
        e["payload"]["action_id"]
        for e in events
        if e["event_type"] == "action"
    }
    for event in events:
        if event["event_type"] == "observation":
            action_id = event["payload"].get("action_id")
            if action_id not in action_ids:
                problems.append(f"observation 无对应 action: {action_id}")
    if problems:
        for problem in problems:
            print(f"FAIL: {problem}")
        return 1
    print(
        f"OK: {len(events)} 事件，sequence 单调，无孤儿引用，observation 全部可解析"
    )
    return 0


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
        print(
            "需提供 --action N 或 --action-id <id> 或 --check", file=sys.stderr
        )
        return 1

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
