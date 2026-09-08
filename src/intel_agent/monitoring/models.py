"""Monitor domain models (spec 002 §3)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from ..contracts._time import AwareDatetime, JsonValue, require_aware
from ..contracts.documents import Citation

MonitorStatus = Literal["active", "paused"]
MonitorTrigger = Literal["scheduled", "manual"]
ChangeKind = Literal["new_fact", "changed_fact", "removed_fact", "new_source"]
Importance = Literal["high", "normal"]


class MonitorSchedule(BaseModel):
    cadence: Literal["daily", "weekly"]
    local_time: str  # HH:MM
    timezone: str  # IANA
    weekday: int | None = Field(default=None, ge=0, le=6)


class Monitor(BaseModel):
    monitor_id: str
    name: str
    subject: str
    strategy: str
    questions: list[str] = Field(default_factory=list)
    websites: list[str] = Field(default_factory=list)
    schedule: MonitorSchedule
    status: MonitorStatus = "active"
    config_version: int = Field(default=1, ge=1)
    baseline_run_id: str | None = None
    active_run_id: str | None = None
    next_run_at: AwareDatetime | None = None
    last_run_at: AwareDatetime | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @field_validator("next_run_at", "last_run_at", "created_at", "updated_at")
    @classmethod
    def _aware(cls, value: datetime | None) -> datetime | None:
        return require_aware(value) if value is not None else None


class MonitorRun(BaseModel):
    run_id: str
    monitor_id: str
    task_id: str
    trigger: MonitorTrigger
    scheduled_for: AwareDatetime | None = None
    input_snapshot: dict[str, Any] = Field(default_factory=dict)
    baseline_run_id: str | None = None
    initial_baseline: bool = False
    summary: str = ""
    limitations: list[str] = Field(default_factory=list)

    @field_validator("scheduled_for")
    @classmethod
    def _aware(cls, value: datetime | None) -> datetime | None:
        return require_aware(value) if value is not None else None


class FactVersion(BaseModel):
    """An immutable observation of a fact within a monitor's baseline."""

    fact_version_id: str
    monitor_id: str
    created_run_id: str
    fact_key: str
    subject: str = ""
    predicate: str = ""
    scope: JsonValue = Field(default_factory=dict)
    value: JsonValue = Field(default_factory=dict)
    statement: str
    previous_version_id: str | None = None
    citations: list[Citation] = Field(default_factory=list)


class MonitorChange(BaseModel):
    change_id: str
    run_id: str
    kind: ChangeKind
    previous_version_id: str | None = None
    current_version_id: str | None = None
    source_key: str | None = None
    citation: Citation | None = None
    importance: Importance = "normal"
    importance_reason: str = ""
    summary: str
    created_at: AwareDatetime

    @field_validator("created_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        return require_aware(value)


class MonitorRunView(BaseModel):
    """Read projection of a run plus its task state."""

    run: MonitorRun
    status: str
    phase: str | None = None
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None
    error: JsonValue | None = None
    changes: list[MonitorChange] = Field(default_factory=list)


class MonitorDetail(BaseModel):
    monitor: Monitor
    runs: list[MonitorRunView] = Field(default_factory=list)
