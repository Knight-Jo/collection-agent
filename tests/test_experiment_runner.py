"""Experiment CLI must run the settings recorded in its manifest."""

from __future__ import annotations

import json
import sys

from scripts import run_experiment


def test_experiment_forwards_run_limits_and_deep_crawl(monkeypatch, tmp_path):
    commands: list[list[str]] = []

    class Process:
        returncode = 0

        def __init__(self, command, **_kwargs):
            commands.append(command)

        def wait(self):
            return None

    monkeypatch.setattr(run_experiment, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(run_experiment, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(run_experiment.subprocess, "Popen", Process)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_experiment.py",
            "--name",
            "limits",
            "--topic",
            "主题",
            "--questions",
            "问题甲",
            "问题乙",
            "--max-turns",
            "40",
            "--dry",
            "3",
            "--deep-crawl",
            "--objective",
            "验证产业进展",
            "--time-range",
            "2024-2026",
            "--geography",
            "中国",
            "--language",
            "zh-CN",
            "en",
            "--report-depth",
            "deep",
            "--benchmark-id",
            "benchmark-v1",
            "--case-id",
            "policy-001",
            "--model-id",
            "local-27b",
            "--repeat",
            "2",
        ],
    )

    assert run_experiment.main() == 0
    command = next(command for command in commands if "intel_agent" in command)
    assert command[command.index("--max-turns") + 1] == "40"
    assert command[command.index("--max-tool-calls") + 1] == "3"
    assert "--deep-crawl" in command
    assert command[command.index("--objective") + 1] == "验证产业进展"
    assert command[command.index("--time-range") + 1] == "2024-2026"
    assert command[command.index("--geography") + 1] == "中国"
    assert command[
        command.index("--language") + 1 : command.index("--report-depth")
    ] == ["zh-CN", "en"]
    assert command[command.index("--report-depth") + 1] == "deep"
    manifest = json.loads(
        (tmp_path / "runs" / "001-limits" / "manifest.json").read_text()
    )
    assert manifest["evaluation"] == {
        "benchmark_id": "benchmark-v1",
        "case_id": "policy-001",
        "model_id": "local-27b",
        "repeat": 2,
    }
    assert manifest["objective"] == "验证产业进展"
    assert manifest["scope"] == {
        "time_range": "2024-2026",
        "geography": ["中国"],
        "languages": ["zh-CN", "en"],
    }
    assert manifest["report_depth"] == "deep"


def test_experiment_accepts_topic_only_and_defaults_to_full_budget(
    monkeypatch, tmp_path
):
    commands: list[list[str]] = []

    class Process:
        returncode = 0

        def __init__(self, command, **_kwargs):
            commands.append(command)

        def wait(self):
            return None

    monkeypatch.setattr(run_experiment, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(run_experiment, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(run_experiment.subprocess, "Popen", Process)
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_experiment.py", "--name", "topic-only", "--topic", "主题"],
    )

    assert run_experiment.main() == 0
    command = next(command for command in commands if "intel_agent" in command)
    assert command[command.index("--max-turns") + 1] == "200"
    assert command[command.index("--questions") + 1] == "--cwd"


def test_trace_summary_records_current_run_identity_and_usage(tmp_path):
    trace = tmp_path / "trace.jsonl"
    trace.write_text(
        "\n".join(
            (
                json.dumps(
                    {
                        "run_id": "run-1",
                        "task_id": None,
                        "event_type": "model_call",
                        "payload": {"model": "model-a"},
                    }
                ),
                json.dumps(
                    {
                        "run_id": "run-1",
                        "task_id": "task-1",
                        "event_type": "run_finished",
                        "payload": {
                            "stage": "done",
                            "requests": 12,
                            "tool_calls": 20,
                            "input_tokens": 100,
                            "output_tokens": 25,
                            "total_tokens": 125,
                        },
                    }
                ),
                "truncated-json",
            )
        ),
        encoding="utf-8",
    )

    assert run_experiment._trace_summary(trace) == {
        "trajectory_run_id": "run-1",
        "task_id": "task-1",
        "model": "model-a",
        "final_stage": "done",
        "usage": {
            "requests": 12,
            "tool_calls": 20,
            "input_tokens": 100,
            "output_tokens": 25,
            "total_tokens": 125,
        },
    }


def test_experiment_preserves_early_failure_without_intel_state(
    monkeypatch, tmp_path
):
    class Process:
        returncode = 1

        def __init__(self, _command, **_kwargs):
            log_dir = tmp_path / "runs/001-early-failure/data/logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            (log_dir / "agent.log").write_text("missing model key")

        def wait(self):
            return None

    monkeypatch.setattr(run_experiment, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(run_experiment, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(run_experiment.subprocess, "Popen", Process)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_experiment.py",
            "--name",
            "early-failure",
            "--topic",
            "主题",
        ],
    )

    assert run_experiment.main() == 1
    run_dir = tmp_path / "runs/001-early-failure"
    assert (run_dir / "data_snapshot/logs/agent.log").exists()
    assert (
        json.loads((run_dir / "manifest.json").read_text())["exit_code"] == 1
    )


def test_experiment_rejects_partial_evaluation_metadata_before_creating_run(
    monkeypatch, tmp_path
):
    runs_dir = tmp_path / "runs"
    monkeypatch.setattr(run_experiment, "RUNS_DIR", runs_dir)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_experiment.py",
            "--name",
            "invalid-metadata",
            "--topic",
            "主题",
            "--questions",
            "问题甲",
            "问题乙",
            "--benchmark-id",
            "benchmark-v1",
        ],
    )

    assert run_experiment.main() == 1
    assert not runs_dir.exists()
