"""Application logging configuration and instrumentation tests."""

from __future__ import annotations

import logging

import pytest

from intel_agent import logging as agent_logging
from intel_agent.agent import _failure
from intel_agent.config import Settings
from intel_agent.models import IntelError, SufficiencyCriteria
from intel_agent.task import create_task, record_search_attempt


@pytest.fixture(autouse=True)
def _reset_logging():
    yield
    agent_logging._configured = False
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    root.setLevel(logging.WARNING)
    for name in ("httpx", "httpcore", "openai", "urllib3", "uvicorn"):
        logging.getLogger(name).setLevel(logging.NOTSET)


def test_configure_logging_writes_timestamped_file(tmp_path):
    settings = Settings()
    agent_logging.configure_logging(tmp_path, settings)
    logging.getLogger("probe").info("hello")

    files = list((tmp_path / "data" / "logs").glob("agent-*.log"))
    assert len(files) == 1
    assert "hello" in files[0].read_text(encoding="utf-8")

    # Idempotent: a repeat call adds neither a new file nor duplicate handlers.
    agent_logging.configure_logging(tmp_path, settings)
    assert len(list((tmp_path / "data" / "logs").glob("agent-*.log"))) == 1
    assert logging.getLogger().level == logging.INFO


def test_configure_logging_level_override_opens_debug(tmp_path):
    agent_logging.configure_logging(tmp_path, Settings(), "DEBUG")

    assert logging.getLogger().level == logging.DEBUG
    assert logging.getLogger("httpx").level == logging.DEBUG


def test_failure_logs_error(caplog):
    with caplog.at_level(logging.ERROR, logger="intel_agent.agent"):
        result = _failure(IntelError("UNSAFE_URL", "拒绝访问"))

    assert result["error"]["code"] == "UNSAFE_URL"
    assert "tool failed code=UNSAFE_URL" in caplog.text


def test_logging_redacts_sensitive_url_query(tmp_path):
    agent_logging.configure_logging(tmp_path, Settings())
    logger = logging.getLogger("probe")
    logger.info("fetch %s", "https://example.com/?token=secret&ok=1")

    log_file = next((tmp_path / "data" / "logs").glob("agent-*.log"))
    content = log_file.read_text(encoding="utf-8")
    assert "token=secret" not in content
    assert "token=***" in content


def test_budget_exhaustion_logs_warning(caplog, cwd):
    task = create_task(
        cwd, "主题", ["问题一", "问题二"], SufficiencyCriteria()
    )
    from intel_agent.task import SEARCH_POOL_SHARES

    cap = max(1, int(6 * SEARCH_POOL_SHARES["discovery"]))
    for _ in range(cap):
        record_search_attempt(cwd, task.id)

    with (
        caplog.at_level(logging.WARNING, logger="intel_agent.task"),
        pytest.raises(IntelError) as error,
    ):
        record_search_attempt(cwd, task.id)

    assert error.value.code == "SEARCH_BUDGET_EXHAUSTED"
    assert "search budget exhausted" in caplog.text
