"""Configuration tests for remote/local models and bounded context."""

import pytest
from pydantic import ValidationError

from intel_agent.config import ContextConfig, Settings


@pytest.mark.parametrize(
    ("window", "history_bytes", "tool_bytes"),
    [
        (16_384, 24_576, 4_096),
        (32_768, 49_152, 8_192),
        (65_536, 98_304, 16_384),
        (131_072, 196_608, 32_768),
        (262_144, 393_216, 65_536),
    ],
)
def test_context_window_profiles_derive_bounded_payloads(
    window, history_bytes, tool_bytes
):
    config = ContextConfig(context_window_tokens=window)

    assert config.history_max_bytes() == history_bytes
    assert config.tool_content_max_bytes() == tool_bytes


def test_context_window_rejects_unsupported_size():
    with pytest.raises(ValidationError):
        ContextConfig.model_validate({"context_window_tokens": 8_192})


def test_context_audit_bounds_have_sane_defaults():
    config = ContextConfig()

    assert config.audit_concurrency == 2
    assert config.audit_timeout_seconds == 60.0

    with pytest.raises(ValidationError):
        ContextConfig.model_validate({"audit_concurrency": 0})
    with pytest.raises(ValidationError):
        ContextConfig.model_validate({"audit_timeout_seconds": 0})


def test_keyless_openai_compatible_model_is_configured():
    settings = Settings.model_validate(
        {
            "model": {
                "name": "Qwen3.5-9B",
                "base_url": "http://127.0.0.1:9876/v1",
                "api_key_env": None,
            }
        }
    )

    assert settings.model_api_key() == "local"
    assert settings.audit_api_key() == "local"


def test_remote_model_still_requires_its_configured_environment(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    assert Settings().model_api_key() is None


def test_settings_only_exposes_effective_options():
    settings = Settings()

    assert not hasattr(settings, "storage")
    assert not hasattr(settings.search.github, "timeout")
    assert not hasattr(settings.search.github, "retry")
    assert not hasattr(settings.search.archive, "wayback")
