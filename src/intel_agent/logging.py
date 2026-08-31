"""Application logging configuration and logger factory (stdlib logging).

Logs are the *technical* observation surface: run lifecycle, per-step model
calls, warnings (budgets, fallbacks, robots), and errors. Business decisions
and state changes stay in the structured trajectory (``trajectory.py``) — this
module deliberately does not re-log them.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from pathlib import Path

from .config import Settings

# Third-party loggers that are quieted to WARNING unless DEBUG is requested,
# so their HTTP/retry noise only surfaces with ``--log-level DEBUG``.
_NOISY_LOGGERS = ("httpx", "httpcore", "openai", "urllib3", "uvicorn")

_configured = False
_SECRET_URL_RE = re.compile(
    r"([?&](?:api_key|auth|key|secret|signature|token|password)=)[^&#\s]*",
    re.IGNORECASE,
)


class _RedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _SECRET_URL_RE.sub(r"\1***", str(record.msg))
        if record.args:
            record.args = tuple(
                _SECRET_URL_RE.sub(r"\1***", value)
                if isinstance(value, str)
                else value
                for value in (
                    record.args
                    if isinstance(record.args, tuple)
                    else (record.args,)
                )
            )
        return True


def get_logger(name: str) -> logging.Logger:
    """Return a logger named by the caller's module (``intel_agent.<module>``)."""
    return logging.getLogger(name)


def configure_logging(
    cwd: Path, settings: Settings, level_override: str | None = None
) -> None:
    """Configure the root logger once; idempotent across repeated calls.

    Streams to stderr and to a timestamped file under ``settings.logging.dir``
    (one file per process start). A repeat call only re-applies the level so a
    later ``--log-level DEBUG`` overrides without duplicating handlers.
    """
    global _configured
    level_name = (level_override or settings.logging.level).upper()
    level = getattr(logging, level_name, logging.INFO)
    root = logging.getLogger()

    if _configured:
        root.setLevel(level)
        for handler in root.handlers:
            handler.setLevel(level)
        return

    root.setLevel(level)
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)-8s] [%(name)s] %(message)s"
    )
    stderr = logging.StreamHandler()
    stderr.setLevel(level)
    stderr.setFormatter(formatter)
    stderr.addFilter(_RedactionFilter())
    root.addHandler(stderr)

    log_dir = cwd / settings.logging.dir
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    file_handler = logging.FileHandler(
        log_dir / f"agent-{timestamp}.log", encoding="utf-8"
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    file_handler.addFilter(_RedactionFilter())
    root.addHandler(file_handler)

    third_party_level = (
        logging.DEBUG if level <= logging.DEBUG else logging.WARNING
    )
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(third_party_level)

    _configured = True
