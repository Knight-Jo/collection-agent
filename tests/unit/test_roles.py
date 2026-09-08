"""Thinking-level resolution tests (role config)."""

from __future__ import annotations

import httpx2

from intel_agent.agent.roles import DEFAULT_THINKING, resolve_thinking


class _Model:
    def __init__(self, disable=False, thinking=None, role_thinking=None):
        self.disable_thinking = disable
        self.thinking = thinking
        self.role_thinking = role_thinking or {}


class _Settings:
    def __init__(self, model):
        self.model = model


def test_disable_thinking_master_switch_wins():
    settings = _Settings(_Model(disable=True, thinking="high"))
    assert resolve_thinking(settings, "planner") is False


def test_role_override_beats_global():
    settings = _Settings(
        _Model(thinking="high", role_thinking={"writer": "low"})
    )
    assert resolve_thinking(settings, "writer") == "low"
    assert resolve_thinking(settings, "planner") == "high"


def test_global_thinking_applies_to_all_roles():
    settings = _Settings(_Model(thinking="medium"))
    assert resolve_thinking(settings, "planner") == "medium"
    assert resolve_thinking(settings, "writer") == "medium"


def test_default_per_role_when_unset():
    settings = _Settings(_Model())
    assert resolve_thinking(settings, "planner") == DEFAULT_THINKING["planner"]
    assert resolve_thinking(settings, "writer") == DEFAULT_THINKING["writer"]


def test_build_model_wires_timeout_and_retries():
    from intel_agent.agent.models import build_model
    from intel_agent.runtime.config import ModelConfig, ResearchSettings

    settings = ResearchSettings(
        model=ModelConfig(request_timeout_seconds=321.0, max_retries=4)
    )
    model = build_model(settings)
    client = model.client  # type: ignore[attr-defined]  # openai model exposes the SDK client
    assert client.timeout == httpx2.Timeout(321.0)
    assert client.max_retries == 4
