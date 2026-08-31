"""迭代实验运行器：执行一次情报收集实验并保存全部轨迹与产物。

用法:
  python scripts/run_experiment.py --name baseline --topic "低空经济" \
      --questions "2026年低空经济投资与融资趋势" "亿航智能商业化进展与订单情况" \
      [--recency 120] [--min-sources 2] [--min-quality 1] [--max-turns 200] [--dry 1]

每次实验保存到 experiments/runs/<序号>-<name>/：
  manifest.json   实验配置与任务元数据
  trace.jsonl     完整 agent 消息轨迹（模型请求/工具调用/结果）
  run.log         CLI 输出
  state/          data/intel 状态快照（含 SQLite 主状态）
  output/         证据包与研判报告
  REPORT.md       实验报告（由分析阶段生成）
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = PROJECT_ROOT / "experiments" / "runs"


def _next_run_number() -> int:
    existing = [
        int(p.name.split("-")[0])
        for p in RUNS_DIR.iterdir()
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


def _trace_summary(path: Path) -> dict[str, object]:
    """Extract stable run identity and usage from an incremental trace."""
    if not path.exists():
        return {}
    summary: dict[str, object] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("run_id"):
            summary["trajectory_run_id"] = event["run_id"]
        if event.get("task_id"):
            summary["task_id"] = event["task_id"]
        payload = event.get("payload", {})
        if event.get("event_type") == "model_call" and payload.get("model"):
            summary.setdefault("model", payload["model"])
        if event.get("event_type") == "run_finished":
            summary["final_stage"] = payload.get("stage")
            summary["usage"] = {
                key: payload.get(key)
                for key in (
                    "requests",
                    "tool_calls",
                    "input_tokens",
                    "output_tokens",
                    "total_tokens",
                )
            }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--name",
        required=True,
        help="实验名称（如 baseline / fix-repetition）",
    )
    parser.add_argument("--topic", required=True)
    parser.add_argument("--questions", nargs="*", default=[])
    parser.add_argument("--objective", default="")
    parser.add_argument("--time-range", default="")
    parser.add_argument("--geography", nargs="*", default=[])
    parser.add_argument("--language", nargs="*", default=[])
    parser.add_argument(
        "--report-depth",
        choices=("brief", "standard", "deep"),
        default="standard",
    )
    parser.add_argument("--recency", type=int, default=120)
    parser.add_argument("--min-sources", type=int, default=2)
    parser.add_argument("--min-quality", type=int, default=1)
    parser.add_argument("--max-turns", type=int, default=200)
    parser.add_argument(
        "--dry",
        type=int,
        default=0,
        help="前 N 个工具轮次后中止（调试用，0=完整运行）",
    )
    parser.add_argument(
        "--max-tool-calls",
        type=int,
        default=None,
        help="agent 最大工具调用数（None=不限制）",
    )
    parser.add_argument("--config", default=None, help="config.yaml 路径")
    parser.add_argument(
        "--deep-crawl", action="store_true", help="启用深度抓取（BFS 爬虫）"
    )
    parser.add_argument("--benchmark-id")
    parser.add_argument("--case-id")
    parser.add_argument("--model-id")
    parser.add_argument("--repeat", type=int, default=1)
    args = parser.parse_args()
    if len(args.questions) == 1 or len(args.questions) > 6:
        print("错误: questions 数量必须为 0 或 2-6 个", file=sys.stderr)
        return 1
    evaluation_fields = (args.benchmark_id, args.case_id, args.model_id)
    if any(evaluation_fields) and not all(evaluation_fields):
        print(
            "错误: benchmark-id、case-id、model-id 必须同时提供",
            file=sys.stderr,
        )
        return 1
    if any(evaluation_fields) and args.repeat < 1:
        print("错误: repeat 必须大于等于 1", file=sys.stderr)
        return 1

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    number = _next_run_number()
    run_dir = RUNS_DIR / f"{number:03d}-{args.name}"
    run_dir.mkdir(parents=True, exist_ok=True)
    state_dir = run_dir / "state"
    output_dir = run_dir / "output"
    state_dir.mkdir(exist_ok=True)
    output_dir.mkdir(exist_ok=True)

    manifest = {
        "run_number": number,
        "name": args.name,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "git_head": _git_head(),
        "topic": args.topic,
        "objective": args.objective,
        "questions": args.questions,
        "scope": {
            "time_range": args.time_range,
            "geography": args.geography,
            "languages": args.language,
        },
        "report_depth": args.report_depth,
        "criteria": {
            "min_independent_sources": args.min_sources,
            "min_high_quality_sources": args.min_quality,
            "recency_days": args.recency,
            "require_recency": False,
        },
        "max_turns": args.max_turns,
        "dry_after_turns": args.dry or None,
        "max_tool_calls": args.max_tool_calls,
        "deep_crawl": args.deep_crawl or args.report_depth == "deep",
        "config": args.config,
    }
    if all(evaluation_fields):
        manifest["evaluation"] = {
            "benchmark_id": args.benchmark_id,
            "case_id": args.case_id,
            "model_id": args.model_id,
            "repeat": args.repeat,
        }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    env = dict(os.environ)
    python = sys.executable
    cmd = [
        python,
        "-m",
        "intel_agent",
        "--topic",
        args.topic,
        "--questions",
        *args.questions,
        "--cwd",
        str(run_dir),
        "--min-sources",
        str(args.min_sources),
        "--min-quality",
        str(args.min_quality),
        "--recency",
        str(args.recency),
        "--trace",
        str(run_dir / "trace.jsonl"),
        "--conversation",
        str(run_dir / "conversation.json"),
        "--max-turns",
        str(args.max_turns),
    ]
    if args.objective:
        cmd += ["--objective", args.objective]
    if args.time_range:
        cmd += ["--time-range", args.time_range]
    if args.geography:
        cmd += ["--geography", *args.geography]
    if args.language:
        cmd += ["--language", *args.language]
    cmd += ["--report-depth", args.report_depth]
    if args.dry:
        cmd += ["--max-tool-calls", str(args.dry)]
    elif args.max_tool_calls is not None:
        cmd += ["--max-tool-calls", str(args.max_tool_calls)]
    if args.deep_crawl:
        cmd.append("--deep-crawl")
    if args.config:
        cmd += ["--config", args.config]

    log_path = run_dir / "run.log"
    started = time.time()
    with open(log_path, "w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            cmd,
            cwd=PROJECT_ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        proc.wait()
    manifest["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    manifest["elapsed_seconds"] = round(time.time() - started, 1)
    manifest["exit_code"] = proc.returncode
    manifest.update(_trace_summary(run_dir / "trace.jsonl"))
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 快照 state/（含 raw 原文供取证分析）；output/ 已由 agent 直接写入 run_dir/output/
    data_dir = run_dir / "data"
    intel_dir = data_dir / "intel"
    if data_dir.exists():
        shutil.copytree(
            data_dir, run_dir / "data_snapshot", dirs_exist_ok=True
        )
    if intel_dir.exists():
        shutil.copytree(intel_dir, state_dir, dirs_exist_ok=True)

    print(f"实验完成: {run_dir}")
    print(f"  耗时: {manifest['elapsed_seconds']}s  exit={proc.returncode}")
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
