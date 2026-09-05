"""Executor and process management tests (T03)."""

from __future__ import annotations

import sys

import pytest

from intel_agent.contracts.errors import DomainError
from intel_agent.runtime.execution import Executor


@pytest.fixture
async def executor():
    ex = Executor(cpu_concurrency=2, gpu_concurrency=1)
    yield ex
    await ex.close()


async def test_timeout_terminates_owned_process(executor, tmp_path):
    marker = tmp_path / "late.txt"
    script = (
        "import time,pathlib; time.sleep(2); pathlib.Path('late.txt').touch()"
    )
    with pytest.raises(DomainError) as raised:
        await executor.run_process(
            [sys.executable, "-c", script],
            timeout_seconds=0.05,
            cwd=tmp_path,
        )
    assert raised.value.code == "TIMEOUT"
    assert executor.active_process_count == 0
    assert not marker.exists()


async def test_successful_process_returns_stdout(executor):
    result = await executor.run_process(
        [sys.executable, "-c", "print('hello')"], timeout_seconds=5
    )
    assert result.returncode == 0
    assert b"hello" in result.stdout
