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
    manifest = json.loads(
        (tmp_path / "runs" / "001-limits" / "manifest.json").read_text()
    )
    assert manifest["evaluation"] == {
        "benchmark_id": "benchmark-v1",
        "case_id": "policy-001",
        "model_id": "local-27b",
        "repeat": 2,
    }


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
