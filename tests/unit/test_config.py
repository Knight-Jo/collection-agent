"""Configuration and profile identity tests (T01)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from intel_agent.runtime.config import (
    ResearchSettings,
    load_settings,
    profile_id,
)


def test_profile_id_is_order_and_whitespace_independent():
    a = {"backend": "pymupdf", "version": "1.28", "lang": ["eng", "chi_sim"]}
    b = {"version": "1.28", "lang": ["eng", "chi_sim"], "backend": "pymupdf"}
    assert profile_id(a) == profile_id(b)


def test_profile_id_changes_with_version():
    a = {"backend": "pymupdf", "version": "1.28"}
    b = {"backend": "pymupdf", "version": "1.29"}
    assert profile_id(a) != profile_id(b)


def test_profile_id_is_64_hex_chars():
    value = profile_id({"a": 1})
    assert len(value) == 64
    int(value, 16)


def test_settings_reject_unknown_fields():
    with pytest.raises(ValidationError):
        ResearchSettings.model_validate({"bogus_section": True})


def test_limits_are_positive():
    with pytest.raises(ValidationError):
        ResearchSettings(search={"total_limit": 0})


def test_load_settings_resolves_relative_paths(tmp_path):
    file = tmp_path / "config.yaml"
    file.write_text("storage:\n  data_dir: ../data\n", encoding="utf-8")
    settings = load_settings(file)
    assert settings.data_root() == (tmp_path / "../data").resolve()


def test_load_settings_defaults_without_file():
    settings = load_settings(None)
    assert settings.model.model_id
