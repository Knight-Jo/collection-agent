"""Monitor scheduling: next-run computation and the scheduler daemon."""

from __future__ import annotations

import asyncio
import logging
import random
from contextlib import suppress
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ..contracts.errors import DomainError
from .models import MonitorSchedule

logger = logging.getLogger("intel_agent.monitoring.scheduler")


def next_run_after(schedule: MonitorSchedule, now: datetime) -> datetime:
    """Compute the next scheduled run strictly after ``now``.

    Daily runs at local_time in the schedule's IANA timezone; weekly runs on
    the configured weekday. A repeated local time (DST fall-back) runs once; a
    nonexistent local time (spring-forward) is pushed to the first valid
    instant by zoneinfo's fold handling.
    """
    tz = ZoneInfo(schedule.timezone)
    local = now.astimezone(tz)
    hour, minute = map(int, schedule.local_time.split(":"))

    candidate = local.replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )
    if candidate <= local:
        candidate += timedelta(days=1)

    if schedule.cadence == "weekly":
        assert schedule.weekday is not None
        candidate += timedelta(
            days=(schedule.weekday - candidate.weekday()) % 7
        )
        if candidate <= local:
            candidate += timedelta(days=7)

    return candidate


class MonitorScheduler:
    """Submits due monitor runs on a tick loop.

    Nothing else in the system fires ``trigger="scheduled"``; without this
    daemon ``next_run_at`` is bookkeeping only. Each tick selects due
    monitors (active or degraded), shuffles them, caps the burst, and
    staggers submissions by a random jitter so monitors sharing a slot do
    not stampede the search and LLM backends.
    """

    def __init__(
        self,
        monitoring,
        *,
        interval_seconds: float = 60.0,
        jitter_seconds: float = 30.0,
        max_submissions_per_tick: int = 5,
    ) -> None:
        self._monitoring = monitoring
        self._interval = interval_seconds
        self._jitter = jitter_seconds
        self._cap = max_submissions_per_tick
        self._task: asyncio.Task | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if self.running:
            return
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def _run_loop(self) -> None:
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                # A broken tick must not kill the daemon; the next interval
                # retries with fresh state.
                logger.exception("monitor scheduler tick failed")
            await asyncio.sleep(self._interval)

    async def tick(self) -> list[str]:
        """Submit due monitors once; returns the launched run ids."""
        due = self._monitoring.due_monitors()
        random.shuffle(due)
        due = due[: self._cap]
        submitted = await asyncio.gather(
            *(self._submit_with_jitter(monitor) for monitor in due)
        )
        return [run_id for run_id in submitted if run_id]

    async def _submit_with_jitter(self, monitor) -> str | None:
        if self._jitter > 0:
            await asyncio.sleep(random.uniform(0, self._jitter))
        try:
            run = await self._monitoring.submit_run(
                monitor.monitor_id, "scheduled"
            )
            logger.info(
                "scheduled monitor run monitor=%s run=%s",
                monitor.monitor_id,
                run.run_id,
            )
            return run.run_id
        except DomainError as error:
            # CONFLICT (run still active) is routine on slow runs; retry on
            # a later tick once the active run releases its slot.
            logger.warning(
                "scheduled submit skipped monitor=%s code=%s",
                monitor.monitor_id,
                error.code,
            )
            return None
