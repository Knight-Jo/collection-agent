"""Logging configuration tests (spec 002 logging)."""

from __future__ import annotations

import logging

from intel_agent.runtime.config import LoggingConfig, ResearchSettings
from intel_agent.runtime.logging import _resolve_level, configure_logging


def test_logging_config_defaults():
    cfg = LoggingConfig()
    assert cfg.level == "INFO"
    assert cfg.console is True
    assert cfg.file is True


def test_settings_parse_logging_section(tmp_path):
    file = tmp_path / "c.yaml"
    file.write_text("logging:\n  level: DEBUG\n", encoding="utf-8")
    settings = ResearchSettings.model_validate({"logging": {"level": "DEBUG"}})
    assert settings.logging.level == "DEBUG"


def test_resolve_level_maps_and_falls_back():
    assert _resolve_level("debug") == logging.DEBUG
    assert _resolve_level("INFO") == logging.INFO
    assert _resolve_level("bogus") == logging.INFO


def test_configure_logging_creates_file(tmp_path, caplog):
    log_dir = tmp_path / "logs"
    configure_logging("WARNING", log_dir, console=False, file=True)
    root = logging.getLogger()
    logger = logging.getLogger("intel_agent.test")
    logger.warning("hello logging")
    for handler in list(root.handlers):
        root.removeHandler(handler)
    content = (log_dir / "intel_agent.log").read_text(encoding="utf-8")
    assert "hello logging" in content
