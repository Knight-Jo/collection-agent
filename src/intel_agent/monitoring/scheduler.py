"""Monitor scheduling: next-run computation (spec 002 §5)."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .models import MonitorSchedule


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
