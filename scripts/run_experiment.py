"""迭代实验运行器：执行一次情报收集实验并保存全部轨迹与产物。

用法:
  python scripts/run_experiment.py --name baseline --topic "低空经济" \
      --questions "2026年低空经济投资与融资趋势" "亿航智能商业化进展与订单情况" \
      [--recency 120] [--min-sources 2] [--min-quality 1] [--max-turns 40] [--dry 1]

每次实验保存到 experiments/runs/<序号>-<name>/：
  manifest.json   实验配置与任务元数据
  trace.jsonl     完整 agent 消息轨迹（模型请求/工具调用/结果）
  run.log         CLI 输出
  state/          data/intel 状态快照
  output/         证据包与研判报告
  REPORT.md       实验报告（由分析阶段生成）
"""

from __future__ import annotations

import argparse
import json
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--name",
        required=True,
        help="实验名称（如 baseline / fix-repetition）",
    )
    parser.add_argument("--topic", required=True)
    parser.add_argument("--questions", nargs="+", required=True)
    parser.add_argument("--recency", type=int, default=120)
    parser.add_argument("--min-sources", type=int, default=2)
    parser.add_argument("--min-quality", type=int, default=1)
    parser.add_argument("--max-turns", type=int, default=40)
    parser.add_argument(
        "--dry",
        type=int,
        default=0,
        help="前 N 个工具轮次后中止（调试用，0=完整运行）",
    )
    parser.add_argument("--config", default=None, help="config.yaml 路径")
    args = parser.parse_args()
    if not 2 <= len(args.questions) <= 6:
        print("错误: questions 数量必须为 2-6 个", file=sys.stderr)
        return 1

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
        "questions": args.questions,
        "criteria": {
            "min_independent_sources": args.min_sources,
            "min_high_quality_sources": args.min_quality,
            "recency_days": args.recency,
            "require_recency": False,
        },
        "max_turns": args.max_turns,
        "dry_after_turns": args.dry or None,
        "config": args.config,
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    env = dict(__import__("os").environ)
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
    ]
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
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 快照 state/（含 raw 原文供取证分析）；output/ 已由 agent 直接写入 run_dir/output/
    if (run_dir / "data").exists():
        shutil.copytree(
            run_dir / "data", run_dir / "data_snapshot", dirs_exist_ok=True
        )
        shutil.copytree(
            run_dir / "data" / "intel", state_dir, dirs_exist_ok=True
        )

    print(f"实验完成: {run_dir}")
    print(f"  耗时: {manifest['elapsed_seconds']}s  exit={proc.returncode}")
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
