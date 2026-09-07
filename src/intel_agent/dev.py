"""Development server: start backend (uvicorn) and frontend (vite) together."""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

logger = logging.getLogger(__file__)


def _repo_root() -> Path:
    candidate = Path(__file__).resolve().parents[2]
    if (candidate / "frontend").exists():
        return candidate
    return Path.cwd()


def main() -> int:
    root = _repo_root()
    env = os.environ.copy()
    env.setdefault(
        "INTEL_AGENT_CONFIG", str(root / "configs" / "default.yaml")
    )
    env["PYTHONPATH"] = (
        str(root / "src") + os.pathsep + env.get("PYTHONPATH", "")
    )
    if env.get("CONDA_PREFIX"):
        env["PATH"] = f"{env['CONDA_PREFIX']}/bin:{env.get('PATH', '')}"

    backend_port = env.get("BACKEND_PORT", "8000")
    backend = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "intel_agent.api.app:create_app",
            "--factory",
            "--host",
            "0.0.0.0",
            "--port",
            backend_port,
            "--workers",
            "1",
        ],
        cwd=root,
        env=env,
    )
    frontend = subprocess.Popen(
        ["bun", "run", "dev", "--host", "0.0.0.0"],
        cwd=root / "frontend",
        env=env,
    )
    procs = [backend, frontend]

    running = True

    def _stop(*_args) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    logger.info(f"backend: http://127.0.0.1:{backend_port}")
    logger.info("frontend: http://localhost:5173")
    logger.info("按 Ctrl+C 退出")

    while running:
        if any(proc.poll() is not None for proc in procs):
            running = False
        time.sleep(0.5)

    for proc in procs:
        if proc.poll() is None:
            proc.terminate()
    for proc in procs:
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    return 0
