"""Thinking-level resolution tests (role config)."""

from __future__ import annotations

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
