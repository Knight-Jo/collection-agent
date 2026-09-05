"""Task locking and orchestrator state (spec §12.3)."""

from __future__ import annotations

from pathlib import Path

from ..contracts.errors import DomainError


class TaskLock:
    """OS-level file lock so only one executor processes a task at a time."""

    def __init__(self, lock_dir: Path, task_id: str) -> None:
        lock_dir.mkdir(parents=True, exist_ok=True)
        self.path = lock_dir / f"{task_id}.lock"
        self._fh = None

    def acquire(self) -> None:
        import fcntl

        self._fh = self.path.open("w")
        try:
            fcntl.flock(self._fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self._fh.close()
            self._fh = None
            raise DomainError(
                "INVALID_REQUEST",
                "task is locked by another executor",
                stage="orchestration",
            ) from error

    def release(self) -> None:
        import fcntl

        if self._fh is not None:
            fcntl.flock(self._fh, fcntl.LOCK_UN)
            self._fh.close()
            self._fh = None
