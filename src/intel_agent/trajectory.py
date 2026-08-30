"""Structured run trajectory: one event stream, three layer projections.

A single source of truth for observability. The agent and its tools emit
``TrajectoryEvent`` objects through :func:`emit`; a :class:`TrajectoryRecorder`
stamps each with the shared envelope (run/task/step/question identity, a
monotonic ``sequence``, OTel span linkage) and persists it. Layers are
projections over the same stream, never separate stores:

- layer "technical": model calls, actions, observations
- layer "business": decisions (model or deterministic) and state mutations
- layer "evaluation": run lifecycle

``intel_state`` remains the authoritative current state; this stream is a
side-band record of what happened, not an event-sourced rebuild of it.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1.0"

Layer = Literal["technical", "business", "evaluation"]
Origin = Literal["model", "deterministic", "policy", "human", "system", "tool"]
EventType = Literal[
    "run_started",
    "model_call",
    "decision",
    "action",
    "observation",
    "state_updated",
    "run_finished",
]
ReasonSource = Literal["rule", "derived", "explicit"]

# Per-run identity, inherited by every event emitted on the same asyncio task.
_run_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "traj_run_id", default=None
)
_task_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "traj_task_id", default=None
)
_step_id_var: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "traj_step_id", default=None
)
_question_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "traj_question_id", default=None
)
_recorder_var: contextvars.ContextVar[Any] = contextvars.ContextVar(
    "traj_recorder", default=None
)

_SENSITIVE_QUERY_KEYS = {
    "api_key",
    "auth",
    "key",
    "secret",
    "signature",
    "token",
}
_SENSITIVE_FIELD_NAMES = {
    "api_key",
    "authorization",
    "auth_token",
    "password",
    "secret",
    "token",
}


def _redact_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: (
                "***"
                if str(key).casefold() in _SENSITIVE_FIELD_NAMES
                else _redact_payload(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_payload(item) for item in value]
    if not isinstance(value, str) or not value.startswith(
        ("http://", "https://")
    ):
        return value
    parsed = urlsplit(value)
    query = [
        (key, "***" if key.casefold() in _SENSITIVE_QUERY_KEYS else item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
    ]
    return urlunsplit(parsed._replace(query=urlencode(query)))


def bind_run(run_id: str) -> None:
    _run_id_var.set(run_id)


def set_task_id(task_id: str) -> None:
    _task_id_var.set(task_id)


def set_step_id(step_id: int) -> None:
    """Set the current decision-cycle id for the async loop and tool threads.

    Contextvars set inside the event-stream loop do not propagate back into the
    agent-graph task that runs tool execution, so the id is also stamped on the
    shared recorder (visible to worker threads that co-emit state changes).
    """
    _step_id_var.set(step_id)
    recorder = current_recorder()
    if recorder is not None:
        recorder.current_step_id = step_id


def reset() -> None:
    """Reset per-run context and version counters (test isolation)."""
    _run_id_var.set(None)
    _task_id_var.set(None)
    _step_id_var.set(None)
    _question_id_var.set(None)
    _recorder_var.set(None)
    with _state_versions_lock:
        _state_versions.clear()


def set_recorder(recorder: TrajectoryRecorder | None) -> None:
    _recorder_var.set(recorder)


def current_recorder() -> TrajectoryRecorder | None:
    return _recorder_var.get()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


# --- payload schemas (one model per event type, not a single mega-model) ---


class RunStartedPayload(BaseModel):
    topic: str = ""
    objective: str = ""
    questions: list[str] = Field(default_factory=list)
    criteria: dict = Field(default_factory=dict)
    report_depth: str = ""


class ModelCallPayload(BaseModel):
    request_index: int
    model: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    finish_reason: str | None = None
    latency_ms: int | None = None


class DecisionPayload(BaseModel):
    decision: str
    reason_codes: list[str] = Field(default_factory=list)
    reason_source: ReasonSource
    reason_summary: str = ""
    selected_action: dict = Field(default_factory=dict)
    state_snapshot: dict = Field(default_factory=dict)


class ActionPayload(BaseModel):
    action_id: str
    tool: str
    action_type: str = ""
    args: object = None


class ObservationPayload(BaseModel):
    action_id: str
    result: dict = Field(default_factory=dict)
    error: str | None = None


class StateUpdatedPayload(BaseModel):
    state_scope: str
    state_id: str | None = None
    version_before: int | None = None
    version_after: int | None = None
    before: dict = Field(default_factory=dict)
    after: dict = Field(default_factory=dict)
    delta: dict = Field(default_factory=dict)
    hash_after: str | None = None


class RunFinishedPayload(BaseModel):
    stage: str = ""
    requests: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    final_coverage: dict = Field(default_factory=dict)


class TrajectoryEvent(BaseModel):
    """Business content of an event; the recorder fills the shared envelope."""

    model_config = ConfigDict(extra="forbid")

    event_type: EventType
    layer: Layer
    origin: Origin
    payload: dict = Field(default_factory=dict)
    parent_event_id: str | None = None
    question_id: str | None = None
    step_id: int | None = None


def make_event(
    event_type: EventType,
    origin: Origin,
    payload: BaseModel | dict,
    *,
    layer: Layer = "business",
    parent_event_id: str | None = None,
    question_id: str | None = None,
    step_id: int | None = None,
) -> TrajectoryEvent:
    data = (
        payload.model_dump(mode="json")
        if isinstance(payload, BaseModel)
        else payload
    )
    return TrajectoryEvent(
        event_type=event_type,
        layer=layer,
        origin=origin,
        payload=_redact_payload(data),
        parent_event_id=parent_event_id,
        question_id=question_id,
        step_id=step_id,
    )


# --- per-run state versioning (single-run scope; not persisted) ---

_state_versions: dict[str, int] = {}
_state_versions_lock = threading.Lock()


def _state_version_key(scope: str, state_id: str | None) -> str:
    return f"{scope}:{state_id}"


def bump_state_version(
    scope: str, state_id: str | None
) -> tuple[int | None, int | None]:
    if state_id is None:
        return None, None
    key = _state_version_key(scope, state_id)
    with _state_versions_lock:
        before = _state_versions.get(key, 0)
        after = before + 1
        _state_versions[key] = after
    return before, after


def canonical_hash(value: dict) -> str:
    """Hash of canonical (key-sorted) JSON, not raw file bytes."""
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _diff(before: dict, after: dict) -> dict:
    return {
        key: {"before": before.get(key), "after": after.get(key)}
        for key in before.keys() | after.keys()
        if before.get(key) != after.get(key)
    }


# --- OTel linkage (lazy; fails closed when opentelemetry is absent) ---


def _otel_span():
    try:
        from opentelemetry import trace
    except Exception:
        return None
    span = trace.get_current_span()
    if span is None or not span.is_recording():
        return None
    return span


def _otel_ids() -> tuple[str | None, str | None]:
    span = _otel_span()
    if span is None:
        return None, None
    ctx = span.get_span_context()
    if not ctx.is_valid:
        return None, None
    return format(ctx.trace_id, "032x"), format(ctx.span_id, "016x")


def _inject_attributes(event_id: str, step_id: int | None) -> None:
    """Attach business identity to the existing OTel span (never nest spans)."""
    span = _otel_span()
    if span is None:
        return
    for name, value in (
        ("business.run_id", _run_id_var.get()),
        ("business.task_id", _task_id_var.get()),
        ("business.step_id", step_id),
        ("business.question_id", _question_id_var.get()),
        ("business.event_id", event_id),
    ):
        if value is not None:
            span.set_attribute(name, value)


# --- recorders ---


class TrajectoryRecorder:
    """A single sink for structured events; implementations own persistence."""

    def __init__(self) -> None:
        self.current_step_id: int | None = None

    def record(self, event: TrajectoryEvent) -> str:
        raise NotImplementedError

    def close(self) -> None:
        pass


class JsonlTrajectoryRecorder(TrajectoryRecorder):
    """Append one envelope JSON object per line; survives abrupt exits.

    Sync tools run in worker threads while the async event loop forwards
    stream events, so ``record`` is guarded by a lock to keep ``sequence``
    monotonic and lines un-interleaved.
    """

    def __init__(self, path: str | Path):
        super().__init__()
        self._stream = Path(path).open("a", encoding="utf-8")  # noqa: SIM115
        self._sequence = 0
        self._lock = threading.Lock()

    def record(self, event: TrajectoryEvent) -> str:
        with self._lock:
            self._sequence += 1
            event_id = f"evt-{uuid.uuid4().hex}"
            otel_trace_id, otel_span_id = _otel_ids()
            step_id = (
                event.step_id
                if event.step_id is not None
                else self.current_step_id
            )
            envelope = {
                "schema_version": SCHEMA_VERSION,
                "run_id": _run_id_var.get(),
                "task_id": _task_id_var.get(),
                "event_id": event_id,
                "sequence": self._sequence,
                "parent_event_id": event.parent_event_id,
                "timestamp": _utc_now(),
                "layer": event.layer,
                "event_type": event.event_type,
                "origin": event.origin,
                "question_id": (
                    event.question_id
                    if event.question_id is not None
                    else _question_id_var.get()
                ),
                "step_id": step_id,
                "otel_trace_id": otel_trace_id,
                "otel_span_id": otel_span_id,
                "payload": event.payload,
            }
            _inject_attributes(event_id, step_id)
            self._stream.write(
                json.dumps(envelope, ensure_ascii=False, default=str) + "\n"
            )
            self._stream.flush()
            self._on_record(envelope)
            return event_id

    def _on_record(self, envelope: dict) -> None:
        """Hook for subclasses to observe each persisted envelope."""

    def close(self) -> None:
        self._stream.close()


def emit(event: TrajectoryEvent) -> str | None:
    """Route an event to the current recorder; no-op when none is bound."""
    recorder = current_recorder()
    return recorder.record(event) if recorder is not None else None


def emit_state_updated(
    scope: str, state_id: str | None, before: dict, after: dict
) -> str | None:
    recorder = current_recorder()
    if recorder is None:
        return None
    version_before, version_after = bump_state_version(scope, state_id)
    payload = StateUpdatedPayload(
        state_scope=scope,
        state_id=state_id,
        version_before=version_before,
        version_after=version_after,
        before=before,
        after=after,
        delta=_diff(before, after),
        hash_after=canonical_hash(after) if after else None,
    )
    return recorder.record(
        make_event("state_updated", "system", payload, layer="business")
    )


def configure_logfire() -> bool:
    """Enable OTel span capture; local-only when no write token is present."""
    try:
        import logfire
    except Exception:
        return False
    try:
        logfire.configure(send_to_logfire=False)
    except TypeError:
        try:
            logfire.configure()
        except Exception:
            return False
    except Exception:
        return False
    return True
