"""Monitor diff/scheduler/source-normalization tests (spec 002 US1-US2)."""

from __future__ import annotations

from datetime import UTC, datetime

from intel_agent.monitoring.diff import (
    derive_fact_key,
    diff_baseline,
    normalize_source_key,
)
from intel_agent.monitoring.models import MonitorSchedule
from intel_agent.monitoring.scheduler import next_run_after


def test_normalize_source_key_lowercases_and_strips_port():
    assert normalize_source_key("https://Example.COM/path") == "example.com"
    assert normalize_source_key("https://a.com:443/x") == "a.com"


def test_derive_fact_key_is_stable_and_value_independent():
    a = derive_fact_key("subj", "pred", {"t": "2026"})
    b = derive_fact_key("subj", "pred", {"t": "2026"})
    c = derive_fact_key("subj", "pred", {"t": "2027"})
    assert a == b
    assert a != c


def test_diff_baseline_classifies_new_changed_matched():
    current = {"k1": "a", "k2": "b2", "k3": "c"}
    baseline = {"k2": "b1", "k3": "c"}
    new, changed, matched = diff_baseline(current, baseline)
    assert new == {"k1"}
    assert changed == {"k2"}
    assert matched == {"k3"}


def test_next_run_daily():
    schedule = MonitorSchedule(
        cadence="daily", local_time="09:00", timezone="UTC"
    )
    now = datetime(2026, 9, 6, 8, 0, tzinfo=UTC)
    nxt = next_run_after(schedule, now)
    assert nxt > now
    assert (nxt.hour, nxt.minute) == (9, 0)
    assert nxt.date().isoformat() == "2026-09-06"


def test_next_run_weekly():
    schedule = MonitorSchedule(
        cadence="weekly", local_time="09:00", timezone="UTC", weekday=0
    )
    now = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)  # Sunday
    nxt = next_run_after(schedule, now)
    assert nxt.weekday() == 0
    assert nxt > now
