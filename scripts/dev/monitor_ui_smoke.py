"""Continuous-monitoring UI smoke test against a live API server.

Drives the same JSON contract the frontend consumes, covering the four
scenarios that need no working LLM (fast, zero token cost):

- S1 gate short-circuit: a seeded watch-source state makes the first run
  skip the research loop via a 304 conditional GET.
- S4 degraded path: a dead source plus the refuse-on-connect LLM endpoint
  fails three runs; the monitor must be flagged degraded with backoff.
- S5 recovery: one successful (gate-skipped) run restores active status.
- S6 auto-scheduling: pushing next_run_at into the past must make the
  scheduler daemon fire a "scheduled" run within one tick.

Prerequisites:
- API server running with configs/test-monitor.yaml (see that file).
- Network access to httpbingo.org (conditional-GET target).

Usage:
    python scripts/dev/monitor_ui_smoke.py --db data/test-monitor-ui.sqlite
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime

WATCH_URL = "https://httpbingo.org/etag/mon-smoke-1"
# httpbingo's /etag/{key} echoes {key} as the ETag and honors If-None-Match;
# quotes are part of the stored validator, exactly as sent.
WATCH_ETAG = '"mon-smoke-1"'
DEAD_URL = "https://this-domain-not-exist-7f3a.invalid/page"


class SmokeFailure(AssertionError):
    pass


def _request(
    base: str, method: str, path: str, body: dict | None = None
) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{base}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = resp.read().decode()
    except urllib.error.HTTPError as error:
        raise SmokeFailure(
            f"{method} {path} -> HTTP {error.code}: {error.read()!r}"
        ) from error
    return json.loads(payload) if payload else {}


def _wait_terminal(
    base: str, monitor_id: str, run_id: str, timeout: float
) -> tuple[dict, dict]:
    """Poll the monitor detail until the run reaches a terminal state."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        detail = _request(base, "GET", f"/monitors/{monitor_id}")
        for view in detail.get("runs", []):
            if view["run"]["run_id"] == run_id:
                status = view.get("status")
                if status in ("succeeded", "failed", "stopped"):
                    return view, detail
        time.sleep(1)
    raise SmokeFailure(f"run {run_id} did not finish within {timeout:.0f}s")


def _seed_watch_source(db: str, monitor_id: str, url: str, etag: str) -> None:
    conn = sqlite3.connect(db, timeout=10)
    try:
        conn.execute("PRAGMA busy_timeout = 10000")
        conn.execute(
            "INSERT OR REPLACE INTO monitor_watch_sources"
            " (monitor_id, url, etag, last_modified, byte_hash, content_hash,"
            " last_checked_at, last_outcome)"
            " VALUES (?, ?, ?, NULL, 'seeded-byte', 'seeded-content',"
            " ?, 'changed')",
            (monitor_id, url, etag, datetime.now(UTC).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def _create_monitor(base: str, name: str, websites: list[str]) -> dict:
    return _request(
        base,
        "POST",
        "/monitors",
        {
            "name": name,
            "subject": "smoke test subject",
            "strategy": "track",
            "schedule": {
                "cadence": "daily",
                "local_time": "09:00",
                "timezone": "UTC",
            },
            "questions": [],
            "websites": websites,
        },
    )


def _trigger(base: str, monitor_id: str, trigger: str = "manual") -> dict:
    return _request(
        base, "POST", f"/monitors/{monitor_id}/runs", {"trigger": trigger}
    )


def scenario_s1_gate_short_circuit(base: str, db: str) -> str:
    started = time.monotonic()
    monitor = _create_monitor(base, "S1 闸门短路", [WATCH_URL])
    monitor_id = monitor["monitor_id"]
    # Seed the watch state so the first run can short-circuit: without a
    # stored validator the gate has no baseline and always reports changed.
    _seed_watch_source(db, monitor_id, WATCH_URL, WATCH_ETAG)
    run = _trigger(base, monitor_id)
    view, detail = _wait_terminal(base, monitor_id, run["run_id"], 60)

    if view["status"] != "succeeded":
        raise SmokeFailure(f"S1: run status {view['status']}, want succeeded")
    gate = view["run"].get("gate_outcome", "")
    if not gate.startswith("skipped:"):
        raise SmokeFailure(f"S1: gate_outcome {gate!r}, want skipped:*")
    if "unchanged" not in gate:
        raise SmokeFailure(f"S1: gate_outcome {gate!r} should be unchanged")
    if "跳过" not in view["run"].get("summary", ""):
        raise SmokeFailure(f"S1: summary {view['run']['summary']!r}")
    if detail["monitor"]["active_run_id"] is not None:
        raise SmokeFailure("S1: active run slot not released")
    return (
        f"S1 gate short-circuit: {gate} in {time.monotonic() - started:.1f}s"
    )


def scenario_s4_degraded(base: str) -> str:
    started = time.monotonic()
    monitor = _create_monitor(base, "S4 降级路径", [DEAD_URL])
    monitor_id = monitor["monitor_id"]
    for index in range(1, 4):
        run = _trigger(base, monitor_id)
        view, _detail = _wait_terminal(base, monitor_id, run["run_id"], 90)
        if view["status"] != "failed":
            raise SmokeFailure(
                f"S4: run {index} status {view['status']}, want failed"
            )
    detail = _request(base, "GET", f"/monitors/{monitor_id}")
    monitor_state = detail["monitor"]
    if monitor_state["status"] != "degraded":
        raise SmokeFailure(
            f"S4: monitor status {monitor_state['status']!r}, want degraded"
        )
    if monitor_state["consecutive_failures"] != 3:
        raise SmokeFailure(
            "S4: consecutive_failures"
            f" {monitor_state['consecutive_failures']}, want 3"
        )
    if monitor_state["next_run_at"] is None:
        raise SmokeFailure("S4: no backoff next_run_at after failures")
    return (
        f"S4 degraded path: status=degraded failures=3 in"
        f" {time.monotonic() - started:.1f}s"
    )


def scenario_s5_recovery(base: str, db: str) -> str:
    started = time.monotonic()
    monitor = _create_monitor(base, "S5 恢复", [DEAD_URL])
    monitor_id = monitor["monitor_id"]
    run = _trigger(base, monitor_id)  # one failure first
    view, _ = _wait_terminal(base, monitor_id, run["run_id"], 90)
    if view["status"] != "failed":
        raise SmokeFailure("S5: setup run did not fail")
    if (
        _request(base, "GET", f"/monitors/{monitor_id}")["monitor"][
            "consecutive_failures"
        ]
        != 1
    ):
        raise SmokeFailure("S5: setup failure count wrong")

    # Point the monitor at a healthy page with a seeded validator, then let
    # a gate-skipped (successful) run reset the health state.
    _request(
        base,
        "PATCH",
        f"/monitors/{monitor_id}",
        {"websites": [WATCH_URL]},
    )
    _seed_watch_source(db, monitor_id, WATCH_URL, WATCH_ETAG)
    run = _trigger(base, monitor_id)
    view, detail = _wait_terminal(base, monitor_id, run["run_id"], 60)
    if view["status"] != "succeeded":
        raise SmokeFailure(f"S5: recovery run status {view['status']}")
    monitor_state = detail["monitor"]
    if monitor_state["status"] != "active":
        raise SmokeFailure(
            f"S5: status {monitor_state['status']!r} after success, want active"
        )
    if monitor_state["consecutive_failures"] != 0:
        raise SmokeFailure("S5: consecutive_failures not reset")
    return f"S5 recovery: active + failures=0 in {time.monotonic() - started:.1f}s"


def scenario_s6_auto_scheduled(base: str, db: str) -> str:
    started = time.monotonic()
    monitor = _create_monitor(base, "S6 自动调度", [WATCH_URL])
    monitor_id = monitor["monitor_id"]
    _seed_watch_source(db, monitor_id, WATCH_URL, WATCH_ETAG)
    run = _trigger(base, monitor_id)  # manual run sets next_run to tomorrow
    _wait_terminal(base, monitor_id, run["run_id"], 60)

    conn = sqlite3.connect(db, timeout=10)
    try:
        conn.execute("PRAGMA busy_timeout = 10000")
        conn.execute(
            "UPDATE monitors SET next_run_at = ? WHERE monitor_id = ?",
            (datetime.now(UTC).isoformat(), monitor_id),
        )
        conn.commit()
    finally:
        conn.close()

    # Scheduler ticks every 5s with zero jitter; the gate then 304s.
    deadline = time.monotonic() + 30
    scheduled_view: dict | None = None
    while time.monotonic() < deadline:
        detail = _request(base, "GET", f"/monitors/{monitor_id}")
        for view in detail.get("runs", []):
            if view["run"]["trigger"] == "scheduled":
                status = view.get("status")
                if status in ("succeeded", "failed", "stopped"):
                    scheduled_view = view
                    break
        if scheduled_view is not None:
            break
        time.sleep(1)
    if scheduled_view is None:
        raise SmokeFailure("S6: no scheduled run fired within 30s")
    if scheduled_view["status"] != "succeeded":
        raise SmokeFailure(
            f"S6: scheduled run status {scheduled_view['status']}"
        )
    if (
        not scheduled_view["run"]
        .get("gate_outcome", "")
        .startswith("skipped:")
    ):
        raise SmokeFailure("S6: scheduled run did not skip research")
    return (
        f"S6 auto-scheduled: fired + skipped in"
        f" {time.monotonic() - started:.1f}s"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--api", default="http://127.0.0.1:8000/api", help="API base URL"
    )
    parser.add_argument(
        "--db", required=True, help="SQLite path the API server uses"
    )
    parser.add_argument(
        "--skip",
        default="",
        help="comma-separated scenario ids to skip (e.g. s4,s6)",
    )
    args = parser.parse_args(argv)

    skip = {name.strip() for name in args.skip.split(",") if name.strip()}
    scenarios: list[tuple[str, Callable[[], str]]] = [
        ("s1", lambda: scenario_s1_gate_short_circuit(args.api, args.db)),
        ("s4", lambda: scenario_s4_degraded(args.api)),
        ("s5", lambda: scenario_s5_recovery(args.api, args.db)),
        ("s6", lambda: scenario_s6_auto_scheduled(args.api, args.db)),
    ]

    failures = 0
    for name, scenario in scenarios:
        if name in skip:
            print(f"[SKIP] {name}")
            continue
        try:
            print(f"[ OK ] {scenario()}")
        except (SmokeFailure, OSError) as error:
            failures += 1
            print(f"[FAIL] {name}: {error}", file=sys.stderr)
    if failures:
        print(f"\n{failures} scenario(s) failed", file=sys.stderr)
        return 1
    print("\nall scenarios passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
