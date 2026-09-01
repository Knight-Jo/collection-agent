"""物化 Web 调研运行为标准归档目录。

用法:
  python scripts/web_run_to_experiment.py --run-id <uuid> --name <name>
  python scripts/web_run_to_experiment.py --latest --name <name>
  python scripts/web_run_to_experiment.py --latest --name <name> --out-dir <dir>

把 data/runs/<run-id>/ 的一次 Web 端 ResearchRun（初始或续研）连同其
task 级资产快照归档为 <out-dir>/<NNN>-<name>/（默认 /tmp/intel-web-runs），
使 analyze_run.py / analyze_trajectory.py 与 CLI 实验共用同一套分析工具链。

快照为 task 级：state/ 含该 task 全部已提交资产（facts/evidence/
coverage/documents/materials/reviews/crawls/search_matrix），与 CLI 实验
的 state/ 语义一致；run 级精确增量需借助 research_checkpoints，首版不做。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = Path("/tmp/intel-web-runs")


def _next_run_number(runs_dir: Path) -> int:
    existing = [
        int(p.name.split("-")[0])
        for p in runs_dir.iterdir()
        if p.is_dir() and p.name.split("-")[0].isdigit()
    ]
    return (max(existing) + 1) if existing else 1


def _git_head() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _connect(cwd: Path) -> sqlite3.Connection:
    path = cwd / "data" / "intel" / "intel.db"
    if not path.exists():
        raise FileNotFoundError(f"找不到 Web 状态库: {path}")
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def _load_run(cwd: Path, run_id: str) -> dict:
    with _connect(cwd) as connection:
        row = connection.execute(
            "SELECT id, task_id, run_type, provenance, status, phase, "
            "outcome, created_at, started_at, completed_at, error, "
            "retry_of_run_id, trigger_message_id "
            "FROM research_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"找不到 run: {run_id}")
        cols = [
            "id",
            "task_id",
            "run_type",
            "provenance",
            "status",
            "phase",
            "outcome",
            "created_at",
            "started_at",
            "completed_at",
            "error",
            "retry_of_run_id",
            "trigger_message_id",
        ]
        return dict(zip(cols, row, strict=True))


def _latest_run_id(cwd: Path) -> str:
    with _connect(cwd) as connection:
        row = connection.execute(
            "SELECT id FROM research_runs ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        if row is None:
            raise ValueError("没有 Web run 记录")
        return row[0]


def _load_task_json(cwd: Path, task_id: str) -> dict:
    with _connect(cwd) as connection:
        row = connection.execute(
            "SELECT task_json FROM task_state WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"找不到 task: {task_id}")
        return json.loads(row[0])


def _trace_summary(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    summary: dict[str, object] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("event_type") == "run_finished":
            payload = event.get("payload", {})
            summary["final_stage"] = payload.get("stage")
            usage = {
                key: payload.get(key)
                for key in (
                    "requests",
                    "tool_calls",
                    "input_tokens",
                    "output_tokens",
                    "total_tokens",
                )
            }
            if any(v is not None for v in usage.values()):
                summary["usage"] = usage
            coverage = payload.get("final_coverage")
            if isinstance(coverage, dict):
                summary["final_coverage"] = coverage
    return summary


def _document_ids_for_task(cwd: Path, task_id: str) -> set[str]:
    """Documents owned by the task, via material digest ∪ evidence refs.

    IntelDocument records carry no task_id; the material digest is the
    authoritative task->document index and evidence ties the rest.
    """
    ids: set[str] = set()
    digest_path = cwd / "data" / "intel" / "materials" / f"{task_id}.json"
    if digest_path.exists():
        digest = json.loads(digest_path.read_text(encoding="utf-8"))
        for item in digest.get("materials", []):
            if item.get("document_id"):
                ids.add(item["document_id"])
    evidence_dir = cwd / "data" / "intel" / "evidence"
    if evidence_dir.exists():
        for path in evidence_dir.glob("*.json"):
            record = json.loads(path.read_text(encoding="utf-8"))
            if record.get("task_id") == task_id and record.get("document_id"):
                ids.add(record["document_id"])
    return ids


def _copy_task_assets(cwd: Path, task_id: str, dest: Path) -> None:
    intel = cwd / "data" / "intel"
    for name in ("facts", "evidence", "reviews"):
        src_dir = intel / name
        if not src_dir.exists():
            continue
        out_dir = dest / name
        out_dir.mkdir(parents=True, exist_ok=True)
        for path in src_dir.glob("*.json"):
            record = json.loads(path.read_text(encoding="utf-8"))
            if record.get("task_id") == task_id:
                shutil.copy2(path, out_dir / path.name)

    coverage_src = intel / "coverage" / f"{task_id}.json"
    if coverage_src.exists():
        (dest / "coverage").mkdir(parents=True, exist_ok=True)
        shutil.copy2(coverage_src, dest / "coverage" / coverage_src.name)

    materials_src = intel / "materials" / f"{task_id}.json"
    if materials_src.exists():
        (dest / "materials").mkdir(parents=True, exist_ok=True)
        shutil.copy2(materials_src, dest / "materials" / materials_src.name)

    crawl_src = intel / "crawls" / f"{task_id}.json"
    if crawl_src.exists():
        (dest / "crawls").mkdir(parents=True, exist_ok=True)
        shutil.copy2(crawl_src, dest / "crawls" / crawl_src.name)

    document_ids = _document_ids_for_task(cwd, task_id)
    if document_ids and (intel / "documents").exists():
        (dest / "documents").mkdir(parents=True, exist_ok=True)
        for document_id in document_ids:
            src = intel / "documents" / f"{document_id}.json"
            if src.exists():
                shutil.copy2(src, dest / "documents" / src.name)

    matrix_src = intel / "search_matrix.json"
    if matrix_src.exists():
        matrix = json.loads(matrix_src.read_text(encoding="utf-8"))
        if matrix.get("task_id") == task_id:
            shutil.copy2(matrix_src, dest / "search_matrix.json")

    conflicts_src = intel / "conflicts.json"
    if conflicts_src.exists():
        shutil.copy2(conflicts_src, dest / "conflicts.json")


def _synthesize_run_log(trace_path: Path, dest: Path) -> None:
    """Trace observations keep error code/message (runner _result_summary);
    reconstruct an analyze_run-compatible error log from them."""
    if not trace_path.exists():
        return
    lines: list[str] = []
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("event_type") != "observation":
            continue
        result = event.get("payload", {}).get("result") or {}
        code = result.get("error_code")
        if not code:
            continue
        message = result.get("error_message") or ""
        lines.append(f"[ERROR] tool failed code={code} message={message}")
    if lines:
        (dest / "run.log").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )


def _copy_outputs(cwd: Path, task: dict, dest: Path) -> None:
    report = (task.get("outputs") or {}).get("report") or {}
    path = report.get("path")
    if not path:
        return
    src = cwd / path
    if src.exists():
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest / src.name)


def _elapsed_seconds(run: dict, trace: dict) -> float | None:
    started = run.get("started_at")
    completed = run.get("completed_at")
    if started and completed:
        try:
            from datetime import datetime

            def parse(value: str) -> datetime:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))

            return round(
                (parse(completed) - parse(started)).total_seconds(), 1
            )
        except ValueError:
            pass
    return None


def materialize(
    cwd: Path, run_id: str, name: str, runs_dir: Path | None = None
) -> Path:
    run = _load_run(cwd, run_id)
    task_id = run["task_id"]
    task = _load_task_json(cwd, task_id)

    trace_src = cwd / "data" / "runs" / run_id / "trace.jsonl"
    trace = _trace_summary(trace_src)

    exit_code = {"succeeded": 0, "failed": 1, "cancelled": 2}.get(
        run["status"]
    )

    manifest: dict[str, object] = {
        "run_number": None,
        "name": name,
        "web_run": True,
        "run_id": run_id,
        "run_type": run["run_type"],
        "provenance": run["provenance"],
        "retry_of_run_id": run["retry_of_run_id"],
        "task_id": task_id,
        "git_head": _git_head(),
        "topic": task.get("topic"),
        "objective": task.get("objective"),
        "questions": [q.get("text") for q in task.get("questions", [])],
        "scope": task.get("scope"),
        "report_depth": task.get("report_depth"),
        "criteria": task.get("criteria"),
        "started_at": run.get("started_at"),
        "finished_at": run.get("completed_at"),
        "elapsed_seconds": _elapsed_seconds(run, trace),
        "exit_code": exit_code,
        "status": run.get("status"),
        "outcome": run.get("outcome"),
        "error": run.get("error"),
    }
    manifest.update(trace)

    runs_dir = runs_dir or RUNS_DIR
    runs_dir.mkdir(parents=True, exist_ok=True)
    number = _next_run_number(runs_dir)
    run_dir = runs_dir / f"{number:03d}-{name}"
    if run_dir.exists():
        raise FileExistsError(f"目标目录已存在: {run_dir}")
    state_dir = run_dir / "state"
    output_dir = run_dir / "output"
    state_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest["run_number"] = number
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if trace_src.exists():
        shutil.copy2(trace_src, run_dir / "trace.jsonl")

    # Shared SQLite carries task_state + research_runs for analyze_run.
    for suffix in ("", "-shm", "-wal"):
        src = cwd / "data" / "intel" / f"intel.db{suffix}"
        if src.exists():
            shutil.copy2(src, state_dir / f"intel.db{suffix}")

    _copy_task_assets(cwd, task_id, state_dir)
    _synthesize_run_log(run_dir / "trace.jsonl", run_dir)
    _copy_outputs(cwd, task, output_dir)
    return run_dir


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", help="ResearchRun id")
    parser.add_argument(
        "--latest", action="store_true", help="物化最近一次 run"
    )
    parser.add_argument("--name", required=True, help="实验名称（归档名）")
    parser.add_argument(
        "--cwd", default=".", help="工作目录（data/intel 相对此目录）"
    )
    parser.add_argument(
        "--out-dir",
        default=str(RUNS_DIR),
        help=f"输出根目录（默认 {RUNS_DIR}）",
    )
    args = parser.parse_args()
    if bool(args.run_id) == bool(args.latest):
        print("错误: --run-id 与 --latest 必须且只能提供一个", file=sys.stderr)
        return 1
    cwd = Path(args.cwd)
    try:
        run_id = args.run_id if args.run_id else _latest_run_id(cwd)
        run_dir = materialize(
            cwd, run_id, args.name, runs_dir=Path(args.out_dir)
        )
    except (ValueError, FileNotFoundError, FileExistsError) as error:
        print(f"物化失败: {error}", file=sys.stderr)
        return 1
    print(f"物化完成: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
