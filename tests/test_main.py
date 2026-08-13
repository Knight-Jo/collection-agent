"""CLI exit status reflects research completion, not only model completion."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import intel_agent.main as main_module
from intel_agent.config import Settings
from intel_agent.task import create_task


@pytest.mark.asyncio
async def test_cli_returns_nonzero_when_agent_stops_before_done(
    monkeypatch, cwd
):
    monkeypatch.setattr(main_module, "load_config", lambda _path: Settings())
    monkeypatch.setattr(Settings, "model_api_key", lambda _self: "key")

    async def fake_run(run_cwd, _settings, spec):
        create_task(run_cwd, spec.topic, spec.questions, spec.criteria)
        return SimpleNamespace(
            output="stopped",
            usage=SimpleNamespace(requests=1, total_tokens=2),
        )

    monkeypatch.setattr(main_module, "run_agent_task", fake_run)
    args = main_module._build_parser().parse_args(
        [
            "--topic",
            "主题",
            "--questions",
            "问题甲",
            "问题乙",
            "--cwd",
            str(cwd),
        ]
    )

    assert await main_module._run(args) == 2
