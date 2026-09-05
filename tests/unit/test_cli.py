"""CLI smoke tests (T19)."""

from __future__ import annotations

from intel_agent.cli import main


def test_preflight_returns_zero(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text(
        f"storage:\n  data_dir: {tmp_path / 'data'}\n"
        f"  output_dir: {tmp_path / 'output'}\n",
        encoding="utf-8",
    )
    assert main(["--config", str(config), "preflight"]) == 0
