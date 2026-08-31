"""Benchmark runner command construction tests."""

import subprocess
import sys
from pathlib import Path

from scripts.evaluate_runs import Benchmark
from scripts.run_benchmark import build_commands, main


def test_script_entrypoint_can_be_run_directly():
    completed = subprocess.run(
        [sys.executable, "scripts/run_benchmark.py", "--help"],
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_build_commands_preserves_case_model_and_repeat_metadata():
    benchmark = Benchmark.model_validate(
        {
            "schema_version": "1.0",
            "benchmark_id": "benchmark-v1",
            "cases": [
                {
                    "case_id": "policy-001",
                    "category": "policy",
                    "topic": "低空经济政策",
                    "questions": [
                        {"question_id": "q1", "text": "问题一", "weight": 1},
                        {"question_id": "q2", "text": "问题二", "weight": 1},
                    ],
                    "must_find_sources": [],
                    "key_facts": [],
                    "known_conflicts": [],
                    "required_media_types": ["pdf"],
                }
            ],
        }
    )

    commands = build_commands(
        benchmark,
        model_id="qwen-local",
        config=Path("experiments/configs/local.yaml"),
        repeats=2,
        max_turns=200,
        deep_crawl=True,
    )

    assert len(commands) == 2
    first = commands[0]
    assert first[first.index("--benchmark-id") + 1] == "benchmark-v1"
    assert first[first.index("--case-id") + 1] == "policy-001"
    assert first[first.index("--model-id") + 1] == "qwen-local"
    assert first[first.index("--repeat") + 1] == "1"
    assert first[
        first.index("--questions") + 1 : first.index("--max-turns")
    ] == [
        "问题一",
        "问题二",
    ]
    assert "--deep-crawl" in first
    assert commands[1][commands[1].index("--repeat") + 1] == "2"


def test_build_commands_sanitizes_case_and_model_for_run_directory_name():
    benchmark = Benchmark.model_validate(
        {
            "schema_version": "1.0",
            "benchmark_id": "benchmark-v1",
            "cases": [
                {
                    "case_id": "policy/001",
                    "category": "policy",
                    "topic": "主题",
                    "questions": [
                        {"question_id": "q1", "text": "问题一", "weight": 1},
                        {"question_id": "q2", "text": "问题二", "weight": 1},
                    ],
                    "must_find_sources": [],
                    "key_facts": [],
                    "known_conflicts": [],
                    "required_media_types": [],
                }
            ],
        }
    )

    command = build_commands(
        benchmark,
        model_id="Qwen/Qwen3.5 27B",
        config=Path("config.yaml"),
        repeats=1,
        max_turns=200,
        deep_crawl=False,
    )[0]

    assert command[command.index("--name") + 1] == (
        "policy-001-Qwen-Qwen3.5-27B-r1"
    )


def test_main_defaults_to_print_only(monkeypatch, capsys):
    project_root = Path(__file__).resolve().parent.parent
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_benchmark.py",
            "--benchmark",
            str(
                project_root
                / "experiments"
                / "evaluation"
                / "benchmark.example.json"
            ),
            "--model-id",
            "local",
            "--config",
            "config.yaml",
            "--repeats",
            "1",
        ],
    )

    assert main() == 0
    assert "scripts/run_experiment.py" in capsys.readouterr().out
