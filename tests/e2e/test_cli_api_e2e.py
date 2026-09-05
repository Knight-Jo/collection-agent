"""CLI and API share one engine and data directory (spec T19, A25)."""

from __future__ import annotations

from pathlib import Path

from intel_agent.cli import main


def _config(tmp_path: Path) -> Path:
    config = tmp_path / "config.yaml"
    config.write_text(
        "storage:\n"
        f"  data_dir: {tmp_path / 'data'}\n"
        f"  output_dir: {tmp_path / 'output'}\n",
        encoding="utf-8",
    )
    return config


def test_cli_prepare_then_status(tmp_path, capsys):
    config = _config(tmp_path)
    assert main(["--config", str(config), "preflight"]) == 0
    capsys.readouterr()
    assert (
        main(
            [
                "--config",
                str(config),
                "run",
                "--question",
                "test question",
                "--prepare-only",
            ]
        )
        == 0
    )
    task_id = capsys.readouterr().out.strip()
    assert task_id
    assert main(["--config", str(config), "status", "--task-id", task_id]) == 0
    out = capsys.readouterr().out
    assert task_id in out
