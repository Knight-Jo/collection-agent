"""Controlled, cancellable execution for CPU/GPU parsing and subprocesses."""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
from dataclasses import dataclass
from pathlib import Path

from ..contracts.errors import DomainError


@dataclass
class ProcessResult:
    returncode: int | None
    stdout: bytes
    stderr: bytes
    timed_out: bool


class Executor:
    """Bounds CPU/GPU concurrency and terminates owned subprocess trees.

    POSIX uses process groups so a timeout or cancel reaps children; Windows
    uses kill-on-close Job Objects via pywin32 (installed under the Windows
    extra). The two must not be treated as equivalent until tested.
    """

    def __init__(
        self, cpu_concurrency: int = 2, gpu_concurrency: int = 1
    ) -> None:
        self._cpu = asyncio.Semaphore(cpu_concurrency)
        self._gpu = asyncio.Semaphore(gpu_concurrency)
        self._active: set[asyncio.subprocess.Process] = set()

    @property
    def active_process_count(self) -> int:
        return len(self._active)

    async def run_process(
        self,
        argv: list[str],
        *,
        timeout_seconds: float,
        cwd: Path | None = None,
    ) -> ProcessResult:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(cwd) if cwd else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        self._active.add(proc)
        try:
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout_seconds
                )
            except TimeoutError:
                await self._terminate(proc)
                raise DomainError(
                    "TIMEOUT",
                    f"process timed out after {timeout_seconds}s",
                    stage="execution",
                ) from None
            return ProcessResult(proc.returncode, stdout, stderr, False)
        finally:
            self._active.discard(proc)

    async def _terminate(self, proc: asyncio.subprocess.Process) -> None:
        with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        with contextlib.suppress(Exception):
            await proc.wait()

    async def run_backend(self, backend, request, *, gpu: bool = False):
        sem = self._gpu if gpu else self._cpu
        async with sem:
            return await backend.run(request)

    async def close(self) -> None:
        for proc in list(self._active):
            await self._terminate(proc)
            self._active.discard(proc)
