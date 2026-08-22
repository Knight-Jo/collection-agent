"""CLI exit status reflects research completion, not only model completion."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import intel_agent.main as main_module
import intel_agent.runner as runner_module
from intel_agent import trajectory
from intel_agent.config import FetchConfig, Settings
from intel_agent.task import create_task
from intel_agent.trajectory import DecisionPayload, make_event


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

    async def fake_run(run_cwd, _settings, spec, **_kwargs):
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


def _trace_lines(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


@pytest.mark.asyncio
async def test_trace_records_events_via_recorder(monkeypatch, cwd, tmp_path):
    monkeypatch.setattr(main_module, "load_config", lambda _path: Settings())
    monkeypatch.setattr(Settings, "model_api_key", lambda _self: "key")
    trace_path = tmp_path / "trace.jsonl"

    async def fake_run(_run_cwd, _settings, _spec, recorder=None, **_kwargs):
        assert recorder is not None
        trajectory.bind_run("run-1")
        trajectory.set_recorder(recorder)
        trajectory.emit(
            make_event(
                "decision",
                "model",
                DecisionPayload(
                    decision="web_search",
                    reason_codes=["LOW_COVERAGE"],
                    reason_source="derived",
                ),
            )
        )
        return SimpleNamespace(
            output="done",
            usage=SimpleNamespace(
                requests=7,
                tool_calls=3,
                input_tokens=100,
                output_tokens=50,
                total_tokens=150,
            ),
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
            "--trace",
            str(trace_path),
        ]
    )

    assert await main_module._run(args) == 2

    lines = _trace_lines(trace_path)
    assert [line["event_type"] for line in lines] == ["decision"]
    assert lines[0]["origin"] == "model"
    assert lines[0]["payload"]["decision"] == "web_search"
    assert lines[0]["payload"]["reason_source"] == "derived"


@pytest.mark.asyncio
async def test_trace_closes_recorder_on_abort(monkeypatch, cwd, tmp_path):
    monkeypatch.setattr(main_module, "load_config", lambda _path: Settings())
    monkeypatch.setattr(Settings, "model_api_key", lambda _self: "key")
    trace_path = tmp_path / "trace.jsonl"

    async def fake_run(_run_cwd, _settings, _spec, recorder=None, **_kwargs):
        trajectory.bind_run("run-1")
        trajectory.set_recorder(recorder)
        trajectory.emit(
            make_event(
                "decision",
                "model",
                DecisionPayload(
                    decision="web_search",
                    reason_codes=[],
                    reason_source="derived",
                ),
            )
        )
        raise asyncio.CancelledError()

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
            "--trace",
            str(trace_path),
        ]
    )

    with pytest.raises(asyncio.CancelledError):
        await main_module._run(args)

    assert [line["event_type"] for line in _trace_lines(trace_path)] == [
        "decision"
    ]


def test_trace_redacts_credential_like_args():
    redacted = runner_module._redact(
        {
            "q": "低空经济",
            "api_key": "secret-value",
            "nested": {"Authorization": "Bearer x", "q": "ok"},
        }
    )

    assert redacted == {
        "q": "低空经济",
        "nested": {"q": "ok"},
    }


def test_trace_redacts_stringified_json_args():
    redacted = runner_module._redact(
        '{"q": "低空经济", "api_key": "secret-value"}'
    )

    assert isinstance(redacted, str)
    assert json.loads(redacted) == {"q": "低空经济"}


def test_analyze_reads_legacy_block_trace(tmp_path):
    from scripts.analyze_run import analyze

    legacy = {
        "events": [
            {"type": "tool_call", "tool": "web_search", "args": {"q": "x"}},
            {"type": "tool_call", "tool": "web_search", "args": {"q": "y"}},
        ],
        "messages": [],
    }
    (tmp_path / "trace.jsonl").write_text(
        json.dumps(legacy, ensure_ascii=False), encoding="utf-8"
    )

    report = analyze(tmp_path)

    assert "工具调用轨迹（共 2 次）" in report
    assert "- web_search: 2" in report


def test_analyze_reads_incremental_jsonl_trace(tmp_path):
    from scripts.analyze_run import analyze

    (tmp_path / "trace.jsonl").write_text(
        '{"type": "tool_call", "tool": "web_fetch", "args": {}}\n'
        '{"type": "usage", "requests": 3, "total_tokens": 10}\n',
        encoding="utf-8",
    )

    report = analyze(tmp_path)

    assert "工具调用轨迹（共 1 次）" in report
    assert "- web_fetch: 1" in report
