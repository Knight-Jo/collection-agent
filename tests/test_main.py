"""CLI exit status reflects research completion, not only model completion."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import intel_agent.main as main_module
from intel_agent.config import FetchConfig, Settings
from intel_agent.task import create_task


def test_cli_accepts_topic_without_questions():
    args = main_module._build_parser().parse_args(["--topic", "测试主题"])

    assert args.topic == "测试主题"
    assert args.questions == []


def test_cli_accepts_optional_research_brief():
    args = main_module._build_parser().parse_args(
        [
            "--topic",
            "测试主题",
            "--objective",
            "了解现状",
            "--time-range",
            "2024-2026",
            "--geography",
            "中国",
            "--language",
            "zh-CN",
            "en",
            "--report-depth",
            "deep",
        ]
    )

    assert args.objective == "了解现状"
    assert args.time_range == "2024-2026"
    assert args.geography == ["中国"]
    assert args.language == ["zh-CN", "en"]
    assert args.report_depth == "deep"


def test_browser_fetch_config_defaults_are_bounded_and_disabled():
    config = FetchConfig()

    assert config.enable_browser_fallback is False
    assert config.browser_network_mode == "validated"
    assert config.browser_timeout_seconds == 15.0
    assert config.browser_max_requests == 40
    assert config.browser_max_bytes == 20_971_520
    assert config.browser_concurrency == 1


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
