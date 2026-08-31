"""Structured run trajectory: one event stream, three layer projections.

A single source of truth for observability. The agent and its tools emit
``TrajectoryEvent`` objects through :func:`emit`; a :class:`TrajectoryRecorder`
stamps each with the shared envelope (run/task/step/question identity, a
monotonic ``sequence``) and persists it. Layers are
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
_investigation_item_id_var: contextvars.ContextVar[str | None] = (
    contextvars.ContextVar("traj_investigation_item_id", default=None)
)
_recorder_var: contextvars.ContextVar[Any] = contextvars.ContextVar(
    "traj_recorder", default=None
)
type ContextBinding = tuple[
    tuple[contextvars.ContextVar[Any], contextvars.Token[Any]], ...
]

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
    _investigation_item_id_var.set(None)
    _recorder_var.set(None)
    with _state_versions_lock:
        _state_versions.clear()


def set_recorder(recorder: TrajectoryRecorder | None) -> None:
    _recorder_var.set(recorder)


def current_recorder() -> TrajectoryRecorder | None:
    return _recorder_var.get()


def bind_context(
    run_id: str,
    recorder: TrajectoryRecorder,
    *,
    task_id: str | None = None,
) -> ContextBinding:
    """Bind one run and return tokens that restore the previous context."""
    recorder.current_step_id = None
    recorder.current_question_id = None
    recorder.current_investigation_item_id = None

    def bind(variable: contextvars.ContextVar[Any], value: Any):
        return variable, variable.set(value)

    return (
        bind(_run_id_var, run_id),
        bind(_task_id_var, task_id),
        bind(_step_id_var, None),
        bind(_question_id_var, None),
        bind(_investigation_item_id_var, None),
        bind(_recorder_var, recorder),
    )


def restore_context(binding: ContextBinding) -> None:
    """Restore a context returned by :func:`bind_context`."""
    for variable, token in reversed(binding):
        variable.reset(token)


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
    status: Literal["succeeded", "failed", "denied", "interrupted"] = (
        "succeeded"
    )
    duration_ms: int | None = Field(default=None, ge=0)
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
    status: Literal["succeeded", "failed", "cancelled"] = "succeeded"
    stage: str = ""
    requests: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    elapsed_ms: int = Field(default=0, ge=0)
    error_code: str | None = None
    error_summary: str | None = None
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
    investigation_item_id: str | None = None
    step_id: int | None = None


def make_event(
    event_type: EventType,
    origin: Origin,
    payload: BaseModel | dict,
    *,
    layer: Layer = "business",
    parent_event_id: str | None = None,
    question_id: str | None = None,
    investigation_item_id: str | None = None,
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
        investigation_item_id=investigation_item_id,
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


# --- recorders ---


def _existing_trace_state(path: Path) -> tuple[int, set[str]]:
    if not path.exists():
        return 0, set()
    sequence = 0
    event_types: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(value, dict):
            continue
        candidate = value.get("sequence")
        if isinstance(candidate, int):
            sequence = max(sequence, candidate)
        event_type = value.get("event_type")
        if isinstance(event_type, str):
            event_types.add(event_type)
    return sequence, event_types


class TrajectoryRecorder:
    """A single sink for structured events; implementations own persistence."""

    def __init__(self) -> None:
        self.current_step_id: int | None = None
        self.current_question_id: str | None = None
        self.current_investigation_item_id: str | None = None
        self.has_run_started = False
        self.has_run_finished = False

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
        trace_path = Path(path)
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        self._sequence, event_types = _existing_trace_state(trace_path)
        self.has_run_started = "run_started" in event_types
        self.has_run_finished = "run_finished" in event_types
        self._stream = trace_path.open("a", encoding="utf-8")  # noqa: SIM115
        if trace_path.stat().st_size:
            with trace_path.open("rb") as existing:
                existing.seek(-1, 2)
                if existing.read(1) != b"\n":
                    self._stream.write("\n")
        self._lock = threading.Lock()

    def record(self, event: TrajectoryEvent) -> str:
        with self._lock:
            self._sequence += 1
            event_id = f"evt-{uuid.uuid4().hex}"
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
                    else self.current_question_id or _question_id_var.get()
                ),
                "investigation_item_id": (
                    event.investigation_item_id
                    if event.investigation_item_id is not None
                    else self.current_investigation_item_id
                    or _investigation_item_id_var.get()
                ),
                "step_id": step_id,
                "payload": event.payload,
            }
            self._stream.write(
                json.dumps(envelope, ensure_ascii=False, default=str) + "\n"
            )
            self._stream.flush()
            self.has_run_started |= event.event_type == "run_started"
            self.has_run_finished |= event.event_type == "run_finished"
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
    scope: str,
    state_id: str | None,
    before: dict,
    after: dict,
    *,
    question_id: str | None = None,
    investigation_item_id: str | None = None,
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
        make_event(
            "state_updated",
            "system",
            payload,
            layer="business",
            question_id=question_id,
            investigation_item_id=investigation_item_id,
        )
    )
