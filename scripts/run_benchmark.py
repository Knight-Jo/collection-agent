"""Run every case in a benchmark with one fixed model configuration."""

from __future__ import annotations

import argparse
import re
import shlex
import subprocess
import sys
from pathlib import Path

if __package__:
    from scripts.evaluate_runs import Benchmark, load_benchmark
else:
    from evaluate_runs import Benchmark, load_benchmark

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _slug(value: str) -> str:
    return re.sub(r"[^\w.-]+", "-", value).strip("-._") or "run"


def build_commands(
    benchmark: Benchmark,
    *,
    model_id: str,
    config: Path,
    repeats: int,
    max_turns: int,
    deep_crawl: bool,
) -> list[list[str]]:
    """Build reproducible single-task experiment commands."""
    commands: list[list[str]] = []
    for case in benchmark.cases:
        for repeat in range(1, repeats + 1):
            name = f"{_slug(case.case_id)}-{_slug(model_id)}-r{repeat}"
            command = [
                sys.executable,
                "scripts/run_experiment.py",
                "--name",
                name,
                "--topic",
                case.topic,
                "--questions",
                *(question.text for question in case.questions),
                "--max-turns",
                str(max_turns),
                "--config",
                str(config),
                "--benchmark-id",
                benchmark.benchmark_id,
                "--case-id",
                case.case_id,
                "--model-id",
                model_id,
                "--repeat",
                str(repeat),
            ]
            if deep_crawl:
                command.append("--deep-crawl")
            commands.append(command)
    return commands


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--max-turns", type=int, default=200)
    parser.add_argument("--deep-crawl", action="store_true")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="实际运行；省略时只打印命令",
    )
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be at least 1")

    commands = build_commands(
        load_benchmark(args.benchmark),
        model_id=args.model_id,
        config=args.config,
        repeats=args.repeats,
        max_turns=args.max_turns,
        deep_crawl=args.deep_crawl,
    )
    for command in commands:
        print(shlex.join(command), flush=True)
        if args.execute:
            completed = subprocess.run(command, cwd=PROJECT_ROOT)
            if completed.returncode:
                return completed.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
