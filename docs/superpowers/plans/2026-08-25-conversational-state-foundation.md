# Conversational State Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the tested SQLite and Pydantic foundation for persistent task conversations, queued actions, research runs, checkpoints, report versions, and durable events.

**Architecture:** Keep existing JSON research assets untouched during this first delivery and introduce SQLite only for new conversational runtime state. Use Python's `sqlite3`, WAL mode, foreign keys, short transactions, and database constraints for single-user Web/background concurrency. A later delivery migrates existing task/document/fact/evidence metadata before runtime cutover, so this phase does not dual-write any existing record type.

**Tech Stack:** Python 3.12, stdlib `sqlite3`, Pydantic 2, pytest.

**Spec:** `docs/architecture/conversational-research-task-architecture.md`

## Global Constraints

- The first release is single-machine and single-user; do not add accounts, roles, authentication, or authorization.
- SQLite lives at `data/intel/intel.db` and enables WAL, foreign keys, and a 5000 ms busy timeout.
- Filesystem JSON remains authoritative for existing research assets until the later offline migration and cutover delivery.
- Do not add an ORM or database dependency.
- Serialized statuses use lowercase values, matching the existing Python/Web models.
- Public APIs have concise English docstrings; comments explain only non-obvious constraints.
- Every database mutation uses a short transaction and preserves task ownership.

---

### Task 1: Persistent state models

**Files:**
- Modify: `src/intel_agent/models.py`
- Create: `tests/test_state_models.py`

**Interfaces:**
- Produces: `Conversation`, `ConversationEpoch`, `Message`, `ActionRequest`, `ResearchRun`, `SearchPlanVersion`, `ResearchCheckpoint`, `ReportVersion`, and `ConversationEvent`.
- Produces status aliases: `MessageStatus`, `ActionRequestStatus`, `ResearchRunStatus`, `CheckpointStatus`, and `ReportVersionStatus`.

- [ ] **Step 1: Write failing construction and validation tests**

```python
import pytest
from pydantic import ValidationError

from intel_agent.models import ActionRequest, Message, ResearchRun


def test_user_message_requires_client_id():
    with pytest.raises(ValidationError):
        Message(
            id="msg-1",
            conversation_id="conversation-1",
            epoch_id="epoch-1",
            sequence=1,
            role="user",
            content="继续搜索",
            status="accepted",
            created_at="2026-08-25T00:00:00+00:00",
        )


def test_proposed_action_has_no_request_mode():
    action = ActionRequest(
        id="action-1",
        task_id="task-1",
        trigger_message_id="msg-1",
        action_type="continue_research",
        immutable_payload={"question_ids": ["q-1"]},
        precondition_committed_state_version=0,
        status="proposed",
        created_at="2026-08-25T00:00:00+00:00",
    )
    assert action.request_mode is None


def test_terminal_run_cannot_be_active():
    with pytest.raises(ValidationError):
        ResearchRun(
            id="run-1",
            task_id="task-1",
            run_type="continue_research",
            input_committed_state_version=0,
            input_snapshot={},
            status="succeeded",
            started_at="2026-08-25T00:00:00+00:00",
        )
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest tests/test_state_models.py -q`

Expected: collection fails because the new model names do not exist.

- [ ] **Step 3: Add the minimum typed models**

Add lower-case `Literal` aliases and Pydantic models to `models.py`. Use one `model_validator(mode="after")` per model only where cross-field rules cannot be expressed by `Field`, including:

```python
MessageRole = Literal["user", "assistant"]
MessageStatus = Literal[
    "accepted", "processing", "completed", "failed", "cancelled"
]
ActionRequestStatus = Literal[
    "proposed", "queued", "executing", "succeeded", "failed",
    "rejected", "expired", "cancelled",
]
ResearchRunStatus = Literal[
    "queued", "running", "succeeded", "failed", "cancelled", "interrupted"
]


class Message(BaseModel):
    id: str
    conversation_id: str
    epoch_id: str
    sequence: int = Field(ge=1)
    client_message_id: str | None = None
    role: MessageRole
    content: str
    status: MessageStatus
    intent: dict[str, object] | None = None
    reply_to_id: str | None = None
    created_at: str
    completed_at: str | None = None
    error: str | None = None


class ActionRequest(BaseModel):
    id: str
    task_id: str
    trigger_message_id: str
    action_type: Literal[
        "continue_research", "search_gap", "search_specific_topic",
        "modify_search_plan", "generate_report", "regenerate_report",
    ]
    immutable_payload: dict[str, object]
    request_mode: Literal["explicit_message", "confirmed_proposal"] | None = None
    request_message_id: str | None = None
    precondition_committed_state_version: int = Field(ge=0)
    precondition_search_plan_version_id: str | None = None
    status: ActionRequestStatus
    created_at: str


class Conversation(BaseModel):
    id: str
    task_id: str
    active_epoch_id: str | None = None
    created_at: str
    updated_at: str


class ConversationEpoch(BaseModel):
    id: str
    conversation_id: str
    sequence: int = Field(ge=1)
    summary: str = ""
    summary_through_sequence: int = Field(default=0, ge=0)
    summary_updated_at: str | None = None
    started_at: str
    archived_at: str | None = None


class ResearchRun(BaseModel):
    id: str
    task_id: str
    run_type: Literal["initial", "continue_research", "retry", "legacy_import"]
    provenance: Literal["native", "migrated"] = "native"
    trigger_message_id: str | None = None
    action_request_id: str | None = None
    retry_of_run_id: str | None = None
    input_committed_state_version: int = Field(ge=0)
    input_snapshot: dict[str, object]
    initial_search_plan_version_id: str | None = None
    active_search_plan_version_id: str | None = None
    status: ResearchRunStatus
    phase: Literal["planning", "collecting", "assessing", "checkpointing"] | None = None
    outcome: Literal["sufficient", "with_gaps"] | None = None
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None


class SearchPlanVersion(BaseModel):
    id: str
    task_id: str
    research_run_id: str
    sequence: int = Field(ge=1)
    plan: dict[str, object]
    trigger_message_id: str | None = None
    action_request_id: str | None = None
    created_at: str


class ResearchCheckpoint(BaseModel):
    id: str
    task_id: str
    research_run_id: str
    sequence: int = Field(ge=1)
    search_plan_version_id: str | None = None
    input_committed_state_version: int = Field(ge=0)
    output_committed_state_version: int | None = Field(default=None, ge=0)
    status: CheckpointStatus
    trigger_action_request_id: str | None = None
    reason: str
    started_at: str
    committed_at: str | None = None


class ReportVersion(BaseModel):
    id: str
    task_id: str
    version: int = Field(ge=1)
    status: ReportVersionStatus
    content_path: str
    content_sha256: str
    based_on_committed_state_version: int = Field(ge=0)
    publication_origin: Literal["native", "legacy_migration"] = "native"
    created_at: str
    published_at: str | None = None
    abandoned_at: str | None = None


class ConversationEvent(BaseModel):
    id: int = Field(ge=1)
    conversation_id: str
    sequence: int = Field(ge=1)
    event_type: str
    data: dict[str, object]
    message_id: str | None = None
    action_request_id: str | None = None
    research_run_id: str | None = None
    created_at: str
```

User messages require `client_message_id`; assistant messages require `status="completed"`, no client ID, and a `reply_to_id`. Proposed actions require null request fields; every other action status requires both request fields. A succeeded/failed/cancelled/interrupted run requires `completed_at`.

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run: `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest tests/test_state_models.py -q`

Expected: all state model tests pass.

- [ ] **Step 5: Commit the model slice**

```bash
git add src/intel_agent/models.py tests/test_state_models.py
git commit -m "feat(conversation): add persistent state models"
```

### Task 2: SQLite schema and connection boundary

**Files:**
- Create: `src/intel_agent/state_db.py`
- Create: `tests/test_state_db.py`
- Modify: `src/intel_agent/storage.py`

**Interfaces:**
- Produces: `state_db_path(cwd: Path) -> Path`.
- Produces: `connect_state_db(cwd: Path) -> sqlite3.Connection`.
- Produces: `initialize_state_db(cwd: Path) -> Path`.
- Consumes: `ensure_intel_dirs(cwd)`.

- [ ] **Step 1: Write failing database initialization tests**

```python
def test_initialize_enables_sqlite_safety_and_schema(cwd):
    path = initialize_state_db(cwd)
    assert path == cwd / "data/intel/intel.db"
    with connect_state_db(cwd) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert {
        "task_state", "conversations", "conversation_epochs", "messages",
        "action_requests", "research_runs", "search_plan_versions",
        "research_checkpoints", "report_versions", "conversation_events",
    } <= tables


def test_partial_indexes_reject_two_running_runs(cwd):
    now = "2026-08-25T00:00:00+00:00"
    initialize_state_db(cwd)
    with connect_state_db(cwd) as connection:
        connection.execute(
            "INSERT INTO task_state(task_id) VALUES (?)", ("task-1",)
        )
        connection.execute(
            "INSERT INTO research_runs(id, task_id, run_type, input_committed_state_version, input_snapshot_json, status, created_at) VALUES (?, ?, ?, 0, '{}', 'running', ?)",
            ("run-1", "task-1", "initial", now),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO research_runs(id, task_id, run_type, input_committed_state_version, input_snapshot_json, status, created_at) VALUES (?, ?, ?, 0, '{}', 'running', ?)",
                ("run-2", "task-1", "continue_research", now),
            )
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest tests/test_state_db.py -q`

Expected: collection fails because `intel_agent.state_db` does not exist.

- [ ] **Step 3: Implement the stdlib SQLite boundary and schema version 1**

`connect_state_db` opens a new connection for each caller, sets `row_factory=sqlite3.Row`, `PRAGMA foreign_keys=ON`, and `PRAGMA busy_timeout=5000`. `initialize_state_db` creates the parent directory, opens the connection, sets WAL, and applies an idempotent schema in one transaction.

The schema must include CHECK constraints for every status and these partial indexes:

```sql
CREATE UNIQUE INDEX one_active_epoch_per_conversation
ON conversation_epochs(conversation_id) WHERE archived_at IS NULL;

CREATE UNIQUE INDEX one_running_run_per_task
ON research_runs(task_id) WHERE status = 'running';

CREATE UNIQUE INDEX one_draft_report_per_task
ON report_versions(task_id) WHERE status = 'draft';

CREATE UNIQUE INDEX one_published_report_per_task
ON report_versions(task_id) WHERE status = 'published';

CREATE UNIQUE INDEX one_client_message_per_conversation
ON messages(conversation_id, client_message_id)
WHERE client_message_id IS NOT NULL;
```

Add `"data/intel/intel.db"`, `"data/intel/intel.db-wal"`, and `"data/intel/intel.db-shm"` parent coverage through the existing `ensure_intel_dirs`; do not add the generated files to Git.

- [ ] **Step 4: Run database tests and verify GREEN**

Run: `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest tests/test_state_db.py -q`

Expected: all schema, PRAGMA, FK, CHECK, and partial-index tests pass.

- [ ] **Step 5: Commit the database slice**

```bash
git add src/intel_agent/state_db.py src/intel_agent/storage.py tests/test_state_db.py
git commit -m "feat(conversation): add sqlite state schema"
```

### Task 3: Conversation and message repository

**Files:**
- Create: `src/intel_agent/state_store.py`
- Create: `tests/test_state_store.py`

**Interfaces:**
- Produces: `StateStore(cwd: Path)`.
- Produces: `StateStore.register_task(task_id: str) -> Conversation`.
- Produces: `StateStore.get_conversation(task_id: str) -> Conversation`.
- Produces: `StateStore.add_user_message(task_id: str, content: str, client_message_id: str) -> Message`.
- Produces: `StateStore.complete_message(user_message_id: str, content: str) -> Message`.
- Produces: `StateStore.start_epoch(task_id: str) -> ConversationEpoch`.
- Produces: `StateStore.list_messages(task_id: str, *, active_epoch_only: bool = True) -> list[Message]`.

- [ ] **Step 1: Write failing repository transaction tests**

```python
def test_message_retry_is_idempotent(cwd):
    store = StateStore(cwd)
    store.register_task("task-1")
    first = store.add_user_message("task-1", "问题", "client-1")
    retried = store.add_user_message("task-1", "问题", "client-1")
    assert retried.id == first.id
    assert [item.sequence for item in store.list_messages("task-1")] == [1]


def test_new_epoch_hides_old_messages_without_deleting_them(cwd):
    store = StateStore(cwd)
    store.register_task("task-1")
    old = store.add_user_message("task-1", "旧问题", "client-1")
    store.start_epoch("task-1")
    new = store.add_user_message("task-1", "新问题", "client-2")
    assert store.list_messages("task-1") == [new]
    assert store.list_messages("task-1", active_epoch_only=False) == [old, new]


def test_complete_message_inserts_one_immutable_assistant_reply(cwd):
    store = StateStore(cwd)
    store.register_task("task-1")
    user = store.add_user_message("task-1", "问题", "client-1")
    assistant = store.complete_message(user.id, "回答")
    assert assistant.role == "assistant"
    assert assistant.reply_to_id == user.id
    assert store.get_message(user.id).status == "completed"
```

- [ ] **Step 2: Run repository tests and verify RED**

Run: `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest tests/test_state_store.py -q`

Expected: collection fails because `StateStore` does not exist.

- [ ] **Step 3: Implement short transactional repository methods**

Use `BEGIN IMMEDIATE` only while assigning a sequence or switching epochs. On duplicate `(conversation_id, client_message_id)`, return the existing row and reject a retry whose content differs with `IntelError("IDEMPOTENCY_CONFLICT", ...)`. `complete_message` updates the user request to completed and inserts the assistant reply in one transaction. Convert rows through private `_row_to_*` helpers; do not expose `sqlite3.Row` outside the module.

- [ ] **Step 4: Run repository and existing storage tests**

Run: `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest tests/test_state_store.py tests/test_storage.py -q`

Expected: all tests pass and existing atomic JSON behavior is unchanged.

- [ ] **Step 5: Commit the conversation store slice**

```bash
git add src/intel_agent/state_store.py tests/test_state_store.py
git commit -m "feat(conversation): persist task messages"
```

### Task 4: Action, run, checkpoint, report, and durable-event transactions

**Files:**
- Modify: `src/intel_agent/state_store.py`
- Modify: `tests/test_state_store.py`

**Interfaces:**
- Produces: `create_action(...) -> ActionRequest`, `confirm_action(...) -> ActionRequest`, and `transition_action(...) -> ActionRequest`.
- Produces: `create_run(...) -> ResearchRun`, `transition_run(...) -> ResearchRun`, and `retry_run(...) -> ResearchRun`.
- Produces: `start_checkpoint(...) -> ResearchCheckpoint` and `commit_checkpoint(...) -> ResearchCheckpoint`.
- Produces: `append_event(...) -> ConversationEvent` and `events_after(...) -> list[ConversationEvent]`.
- Produces: `create_report_draft(...) -> ReportVersion`, `abandon_report(...) -> ReportVersion`, and `publish_report(...) -> ReportVersion`.

- [ ] **Step 1: Write failing lifecycle and constraint tests**

```python
def prepared_store(cwd):
    store = StateStore(cwd)
    store.register_task("task-1")
    return store


def test_confirmed_proposal_queues_once(cwd):
    store = prepared_store(cwd)
    trigger = store.add_user_message("task-1", "现有材料够吗", "client-1")
    action = store.create_action(
        task_id="task-1",
        trigger_message_id=trigger.id,
        action_type="continue_research",
        payload={"question_ids": ["q-1"]},
        proposed=True,
    )
    confirmation = store.add_user_message("task-1", "确认继续搜索", "client-2")
    queued = store.confirm_action(action.id, confirmation.id)
    assert queued.status == "queued"
    assert queued.request_mode == "confirmed_proposal"


def test_retry_creates_new_run_and_keeps_interrupted_terminal(cwd):
    store = prepared_store(cwd)
    first = store.create_run("task-1", "initial", 0, {})
    store.transition_run(first.id, "running")
    interrupted = store.transition_run(first.id, "interrupted")
    retry = store.retry_run(first.id)
    assert interrupted.status == "interrupted"
    assert retry.retry_of_run_id == first.id
    assert retry.id != first.id


def test_checkpoint_commit_advances_version_once(cwd):
    store = prepared_store(cwd)
    run = store.create_run("task-1", "initial", 0, {})
    checkpoint = store.start_checkpoint(run.id, reason="final")
    committed = store.commit_checkpoint(checkpoint.id)
    assert committed.input_committed_state_version == 0
    assert committed.output_committed_state_version == 1
    assert store.committed_state_version("task-1") == 1


def test_stale_report_requires_explicit_flag(cwd):
    store = prepared_store(cwd)
    draft = store.create_report_draft("task-1", "output/report.md", "abc")
    run = store.create_run("task-1", "initial", 0, {})
    checkpoint = store.start_checkpoint(run.id, reason="new evidence")
    store.commit_checkpoint(checkpoint.id)
    with pytest.raises(IntelError, match="报告基于旧研究状态"):
        store.publish_report(draft.id)
```

- [ ] **Step 2: Run lifecycle tests and verify RED**

Run: `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest tests/test_state_store.py -q`

Expected: tests fail because lifecycle methods are missing.

- [ ] **Step 3: Implement explicit transition maps and atomic mutations**

Keep these transition maps as module constants:

```python
RUN_TRANSITIONS = {
    "queued": {"running", "cancelled"},
    "running": {"succeeded", "failed", "cancelled", "interrupted"},
}
ACTION_TRANSITIONS = {
    "proposed": {"queued", "rejected", "expired"},
    "queued": {"executing", "expired", "cancelled"},
    "executing": {"succeeded", "failed", "cancelled"},
}
```

Reject every unlisted transition with `IntelError("INVALID_STATE_TRANSITION", ...)`. A retry always inserts a new queued run linked by `retry_of_run_id`. Checkpoint commit updates checkpoint status and task committed version in one transaction. New drafts atomically abandon the previous draft; publishing atomically supersedes the previous published report and rejects stale drafts unless `publish_stale=True` and the expected current state version still matches.

Persist only durable events. `append_event` assigns a conversation-scoped monotonic sequence under `BEGIN IMMEDIATE`; `events_after` orders by sequence.

- [ ] **Step 4: Run the complete state foundation suite**

Run: `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest tests/test_state_models.py tests/test_state_db.py tests/test_state_store.py tests/test_storage.py -q`

Expected: all tests pass.

- [ ] **Step 5: Run static verification**

```bash
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run ruff format --check src/intel_agent/models.py src/intel_agent/state_db.py src/intel_agent/state_store.py tests/test_state_models.py tests/test_state_db.py tests/test_state_store.py
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run ruff check src/intel_agent/models.py src/intel_agent/state_db.py src/intel_agent/state_store.py tests/test_state_models.py tests/test_state_db.py tests/test_state_store.py
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pyright src/intel_agent/models.py src/intel_agent/state_db.py src/intel_agent/state_store.py tests/test_state_models.py tests/test_state_db.py tests/test_state_store.py
```

Expected: all commands exit 0.

- [ ] **Step 6: Commit the lifecycle slice**

```bash
git add src/intel_agent/state_store.py tests/test_state_store.py
git commit -m "feat(conversation): enforce persistent lifecycles"
```

### Task 5: Foundation documentation and regression verification

**Files:**
- Modify: `docs/architecture/conversational-research-task-architecture.md`
- Modify: `docs/superpowers/plans/2026-08-25-conversational-state-foundation.md`

**Interfaces:**
- Records the implemented schema version and the next delivery boundary.

- [ ] **Step 1: Mark this plan implemented and document the staged boundary**

Add an implementation status noting that SQLite owns only the new conversation runtime records in this delivery. State that existing JSON task/document/fact/evidence data remains unchanged until the offline migration delivery; there is no dual write for any record type.

- [ ] **Step 2: Run project verification**

```bash
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run ruff format --check .
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run ruff check .
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pyright
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run build
```

Expected: every command exits 0.

- [ ] **Step 3: Commit verification records**

```bash
git add docs/architecture/conversational-research-task-architecture.md docs/superpowers/plans/2026-08-25-conversational-state-foundation.md
git commit -m "docs: record conversational state foundation"
```

## Following Deliveries

After this plan passes, create separate executable plans in this order:

1. Offline JSON-to-SQLite research metadata migration and runtime cutover.
2. Task-scoped retrieval, MessageCitation, Dialogue Controller, and Conversation API/SSE.
3. ResearchRun continuation, checkpoint asset commits, and two-slot model scheduling.
4. ReportVersion generation/publishing APIs and the three-column Web workbench.

Do not add code for those deliveries to this plan; each has its own API and acceptance boundary.
