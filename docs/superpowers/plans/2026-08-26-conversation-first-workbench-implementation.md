# Conversation-First Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the topic-form and task-page primary flow with a persistent Conversation-first research workbench supporting intake clarification, research progress, committed-evidence Q&A, run control, versioned reports, and a unified Context Panel.

**Architecture:** A nullable-task Conversation exists before research. A tool-free Intake Agent either answers a capability question, asks for missing scope, or atomically creates and binds an IntelTask plus initial ResearchRun; research and dialogue remain separate runtimes. SQLite stores identity, interaction, run state, transactional events, and timeline projections while large content remains hash-verified on the filesystem.

**Tech Stack:** Python 3.12, stdlib SQLite/asyncio, Pydantic AI, FastAPI SSE, React 19, TypeScript, Bun/Vitest.

**Spec:** `docs/superpowers/specs/2026-08-25-conversation-runtime-web-design.md`

## Global Constraints

- Single machine and single user; add no account, role, authentication, authorization, tenant, or collaboration model.
- `Conversation.task_id` is nullable and not unique; once non-NULL it is immutable.
- Capability and clarification turns call no search, fetch, crawl, or research tools.
- Normal Q&A reads checkpoint-committed assets only.
- `CONTINUE` creates a new ResearchRun; active-run changes use `MODIFY` at a checkpoint.
- `CANCEL` applies only to QUEUED; `STOP` uses RUNNING → STOPPING → STOPPED.
- Durable events share the domain transaction; transient progress is never persisted.
- Event, timeline, and message sequences are distinct.
- Timeline is a rebuildable projection and never a business-state input.
- Historical plans, reports, citations, and checkpoints open by stable ID.
- Preserve filesystem path boundaries and SHA-256 verification.
- Follow RED → GREEN → focused regression → commit for every task.

---

### Task 1: Schema v3 and conversation-first models

**Files:**
- Modify: `src/intel_agent/models.py`
- Modify: `src/intel_agent/state_db.py`
- Modify: `tests/test_state_models.py`
- Modify: `tests/test_state_db.py`

**Interfaces:**
- Produces `ResearchBrief`, `MessageProcessingAttempt`, `TimelineEntry`, nullable-task `Conversation`, leased/stoppable `ResearchRun`, and checkpoint-bound `ReportVersion`.

- [ ] **Step 1: Write failing model tests**

```python
def test_active_conversation_requires_task():
    with pytest.raises(ValidationError):
        Conversation(id="c1", task_id=None, status="active", title="研究", created_at="now", updated_at="now")


def test_report_requires_checkpoint_identity():
    report = make_report(based_on_checkpoint_id="cp7", based_on_committed_state_version=19)
    assert report.based_on_checkpoint_id == "cp7"
```

- [ ] **Step 2: Write failing migration tests**

Create a v2 database, initialize v3, insert two Conversations for one Task,
insert one unbound INTAKE Conversation, reject ACTIVE without a Task, and reject
a second Task using the same `origin_message_id`. Assert the new Brief,
processing-attempt, and timeline tables exist.

- [ ] **Step 3: Verify RED**

Run `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest tests/test_state_models.py tests/test_state_db.py -q`.

- [ ] **Step 4: Implement models and explicit v3 migration**

```python
class ResearchBrief(BaseModel):
    schema_version: Literal["1"] = "1"
    topic: str
    objective: str = ""
    key_questions: list[str] = Field(default_factory=list, max_length=6)
    scope: ResearchScope = Field(default_factory=ResearchScope)
    entities: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    requested_outputs: list[str] = Field(default_factory=lambda: ["research_report"])


class MessageProcessingAttempt(BaseModel):
    id: str
    user_message_id: str
    attempt: int = Field(ge=1)
    status: Literal["accepted", "processing", "completed", "failed", "cancelled"]
    assistant_message_id: str | None = None
    error_code: str | None = None
    error_detail: str | None = None
    started_at: str
    completed_at: str | None = None
```

Use `SCHEMA_V3` to rebuild tables whose old checks or uniqueness cannot be
altered in place. Preserve IDs, run `PRAGMA foreign_key_check`, then record
migration 3.

- [ ] **Step 5: Verify and commit**

Run Step 3, then commit the four Task 1 files with
`feat(conversation): add conversation-first schema`.

---

### Task 2: SQLite task registry and atomic intake binding

**Files:**
- Modify: `src/intel_agent/task.py`
- Modify: `src/intel_agent/state_store.py`
- Modify: `tests/test_task.py`
- Modify: `tests/test_state_store.py`

**Interfaces:**
- Produces `create_conversation()`, `bind_intake_task()`, `list_conversations()`, and `archive_conversation()`.
- Keeps public `load_task()` and task-save signatures stable while moving task identity/status to SQLite.

- [ ] **Step 1: Write failing registry and atomicity tests**

```python
def test_bind_intake_task_is_atomic_and_idempotent(cwd):
    store = StateStore(cwd)
    conversation = store.create_conversation("browser-c1")
    message = store.add_user_message(conversation.id, "调研先进封装", "browser-m1")
    first = store.bind_intake_task(conversation.id, message.id, research_brief("先进封装"))
    second = store.bind_intake_task(conversation.id, message.id, research_brief("先进封装"))
    assert second == first
    assert len(store.list_runs(first.task_id)) == 1
```

Inject failure before commit and assert no Task, Run, binding, event, or
TimelineEntry exists. Add a legacy Task import test that imports once and stops
writing its old JSON metadata.

- [ ] **Step 2: Verify RED**

Run `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest tests/test_task.py tests/test_state_store.py -q`.

- [ ] **Step 3: Centralize task persistence**

Extract `build_task(...) -> IntelTask`. Make `load_task()` and the internal save
function use the SQLite task payload. Import legacy JSON idempotently on first
read and retain the source file as a read-only migration backup.

- [ ] **Step 4: Implement `bind_intake_task`**

Within one `BEGIN IMMEDIATE`: validate INTAKE ownership, insert the immutable
Brief, insert Task payload using unique origin Message, bind/activate the
Conversation, insert Initial Run QUEUED, append `task.created` and `run.queued`,
and create Timeline projections using an independent sequence.

- [ ] **Step 5: Verify and commit**

Run Step 2 plus `tests/test_evidence.py`; commit with
`feat(conversation): bind intake to task atomically`.

---

### Task 3: Intake Agent and processing-attempt runtime

**Files:**
- Create: `src/intel_agent/intake.py`
- Modify: `src/intel_agent/conversation.py`
- Create: `tests/test_intake.py`
- Modify: `tests/test_conversation.py`

**Interfaces:**
- Produces `IntakeDecision`, `IntakeEngine.decide()`, and Conversation-ID based message submission.
- Consumes Task 2 `bind_intake_task()`.

- [ ] **Step 1: Write failing Intake/runtime tests**

```python
async def test_capability_query_keeps_intake_unbound(cwd):
    runtime = runtime_with_intake(cwd, capability("我可以开展公开信息调研。"))
    conversation = runtime.create_conversation()
    await submit_and_wait(runtime, conversation.id, "你能做什么？")
    assert runtime.store.get_conversation(conversation.id).task_id is None
    assert runtime.store.list_runs_for_conversation(conversation.id) == []


async def test_clear_request_binds_one_task(cwd):
    runtime = runtime_with_intake(cwd, start_research("先进封装"))
    conversation = runtime.create_conversation()
    await submit_and_wait(runtime, conversation.id, "调研先进封装产业")
    assert runtime.store.get_conversation(conversation.id).status == "active"
```

Also test clarification, malformed JSON repair, failed processing retry, and
that processing failure never mutates the user Message.

- [ ] **Step 2: Verify RED**

Run `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest tests/test_intake.py tests/test_conversation.py -q`.

- [ ] **Step 3: Implement the tool-free Intake Engine**

```python
class IntakeDecision(BaseModel):
    intent: Literal["capability_query", "clarify_research", "start_research"]
    reply: str
    research_brief: ResearchBrief | None = None
    missing_fields: list[str] = Field(default_factory=list)
```

Use the existing plain-JSON plus one-repair parser. The prompt forbids
networking and unsupported research claims.

- [ ] **Step 4: Refactor ConversationRuntime**

`submit_message(conversation_id, content, client_message_id)` persists user
Message and attempt before scheduling. INTAKE invokes IntakeEngine; ACTIVE
invokes DialogueEngine. Completion atomically creates assistant Message and
completes the attempt. `retry_message(message_id)` creates a new attempt.

- [ ] **Step 5: Verify and commit**

Run Task 3 tests plus `tests/test_dialogue.py`; commit with
`feat(conversation): process intake conversations`.

---

### Task 4: Transactional events, timeline, Run control, and recovery

**Files:**
- Modify: `src/intel_agent/state_store.py`
- Modify: `src/intel_agent/continuation.py`
- Modify: `src/intel_agent/web/runs.py`
- Modify: `tests/test_state_store.py`
- Modify: `tests/test_continuation.py`
- Modify: `tests/test_web_runs.py`

**Interfaces:**
- Produces `events_after(conversation_id, event_sequence)`, `timeline_after(conversation_id, timeline_sequence)`, `stop_run()`, `cancel_queued_run()`, and `recover_abandoned_runs()`.

- [ ] **Step 1: Write failing transaction and cursor tests**

```python
def test_run_stopping_and_event_share_transaction(cwd):
    store, run = running_run(cwd)
    store.stop_run(run.id)
    assert store.get_run(run.id).status == "stopping"
    assert store.events_after(run.conversation_id, 0)[-1].event_type == "run.stopping"


def test_event_and_timeline_sequences_are_independent(cwd):
    event = transition_with_event(store)
    entry = store.timeline_after(event.conversation_id, 0)[0]
    assert entry.source_event_sequence == event.event_sequence
```

Fault-inject before commit and prove both state and event roll back.

- [ ] **Step 2: Write failing Run state/recovery tests**

Assert QUEUED can cancel but not stop; RUNNING can stop but not cancel;
checkpoint after STOPPING raises `RUN_NOT_COMMITTABLE`; expired leases become
INTERRUPTED; retry creates a distinct run with `retry_of_run_id`.

- [ ] **Step 3: Verify RED**

Run `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest tests/test_state_store.py tests/test_continuation.py tests/test_web_runs.py -q`.

- [ ] **Step 4: Implement outbox, projection, and Run semantics**

```python
def _append_durable_event(
    connection: sqlite3.Connection,
    conversation_id: str,
    event_type: str,
    data: dict[str, object],
) -> ConversationEvent:
    ...
```

All domain transitions call this helper before the same transaction commits.
Do not expose a public post-commit event writer. STOP sets cancellation,
prevents new work, and discards results returning after state changed. Startup
recovery uses one process owner UUID and an expiring lease.

- [ ] **Step 5: Verify and commit**

Run Step 3; commit Task 4 files with
`feat(conversation): add auditable run control`.

---

### Task 5: Conversation-first FastAPI and stable Context APIs

**Files:**
- Modify: `src/intel_agent/web/schemas.py`
- Modify: `src/intel_agent/web/conversation.py`
- Modify: `src/intel_agent/web/app.py`
- Modify: `tests/test_web_conversation.py`
- Modify: `tests/test_web_api.py`

**Interfaces:**
- Produces the Conversation-first HTTP/SSE contract from spec sections 6–7.
- Keeps task-scoped Conversation routes as compatibility adapters only.

- [ ] **Step 1: Write failing API contract tests**

```python
created = client.post("/api/conversations", json={}).json()
assert created["status"] == "intake"
assert created["task_id"] is None

accepted = client.post(
    f"/api/conversations/{created['id']}/messages",
    json={"content": "你能做什么？", "client_message_id": "browser-1"},
)
assert accepted.status_code == 202
```

Also cover timeline pagination, `Last-Event-ID`, retry, Run stop/cancel errors,
stable SearchPlanVersion reads, and historical Task lazy Conversation creation.

- [ ] **Step 2: Verify RED**

Run `UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest tests/test_web_conversation.py tests/test_web_api.py -q`.

- [ ] **Step 3: Implement request/read models and routes**

```python
class ConversationCreate(BaseModel):
    client_conversation_id: str | None = None


class ConversationListItem(BaseModel):
    id: str
    task_id: str | None
    status: Literal["intake", "active", "archived"]
    title: str
    updated_at: str
    run_status: str | None
```

Implement Conversation create/list/read/archive, message/retry,
timeline/events, Run stop/cancel, active/versioned SearchPlan reads, and stable
Context object reads. SSE IDs use event sequence only.

- [ ] **Step 4: Add startup recovery and compatibility adapters**

FastAPI lifespan recovers processing attempts and expired Run leases. Old Task
Conversation endpoints resolve or lazily create a bound Conversation and then
delegate, eliminating the first-open SSE 404.

- [ ] **Step 5: Verify and commit**

Run Task 5 tests plus `tests/test_web_runs.py`; commit with
`feat(web): expose conversation-first api`.

---

### Task 6: Frontend data layer and Conversation shell

**Files:**
- Modify: `web/src/types.ts`
- Modify: `web/src/api.ts`
- Modify: `web/src/api.test.ts`
- Modify: `web/src/App.tsx`
- Create: `web/src/pages/ConversationWorkbenchPage.tsx`
- Create: `web/src/pages/ConversationWorkbenchPage.test.tsx`

**Interfaces:**
- Produces Conversation-first TypeScript types/API and `/conversations/:conversationId?` shell.
- Consumes Task 5 HTTP contract.

- [ ] **Step 1: Write failing API and routing tests**

```tsx
render(<App />);
expect(await screen.findByRole("button", { name: "新建对话" })).toBeVisible();
expect(screen.queryByLabelText("研究主题")).not.toBeInTheDocument();
```

Assert API calls use Conversation IDs and Run-specific stop/cancel endpoints.

- [ ] **Step 2: Verify RED**

From `web/`, run
`bun run test -- src/api.test.ts src/pages/ConversationWorkbenchPage.test.tsx`.

- [ ] **Step 3: Implement exact TypeScript contracts and API calls**

```ts
export interface Conversation {
  id: string;
  task_id: string | null;
  status: "intake" | "active" | "archived";
  title: string;
  updated_at: string;
}

export interface TimelineEntry {
  id: string;
  timeline_sequence: number;
  source_event_sequence: number | null;
  type: string;
  data: Record<string, unknown>;
}
```

Do not reuse Run event ID or Message sequence as Timeline cursor.

- [ ] **Step 4: Build the Conversation shell**

```tsx
<Route path="/" element={<ConversationWorkbenchPage />} />
<Route path="/conversations/:conversationId" element={<ConversationWorkbenchPage />} />
<Route path="/new" element={<Navigate to="/" replace />} />
```

Load Conversation history, create INTAKE on “新建对话”, select the latest
active Conversation, and keep the composer available while research runs.

- [ ] **Step 5: Verify and commit**

Run Step 2 and `bun run typecheck`; commit with
`feat(web): add conversation-first shell`.

---

### Task 7: Timeline, RunStatusCard, composer, and reconnect

**Files:**
- Create: `web/src/components/ConversationSidebar.tsx`
- Replace: `web/src/components/ConversationPanel.tsx`
- Create: `web/src/components/RunStatusCard.tsx`
- Create: `web/src/components/ConversationPanel.test.tsx`
- Modify: `web/src/pages/ConversationWorkbenchPage.tsx`

**Interfaces:**
- Produces the central interaction timeline and Run controls.
- Emits stable Context selections consumed by Task 8.

- [ ] **Step 1: Write failing interaction tests**

Cover capability-only intake, clarification, Task creation, pending attempt,
live/committed labels, QUERY while running, MODIFY checkpoint notice, CONTINUE
new Run, STOPPING/STOPPED, retry, and SSE reconnect.

```tsx
expect(screen.getByText("当前处理中 4 项")).toBeVisible();
expect(screen.getByText("已提交：材料 21 · 证据 6")).toBeVisible();
await user.click(screen.getByRole("button", { name: "停止当前调研" }));
expect(api.stopResearchRun).toHaveBeenCalledWith("run-17");
```

- [ ] **Step 2: Verify RED**

Run `bun run test -- src/components/ConversationPanel.test.tsx` from `web/`.

- [ ] **Step 3: Implement sidebar and Timeline rendering**

Render only Conversation titles/status in the sidebar. Map Timeline types to
messages, clarification, action, checkpoint, report, error, and RunStatusCard.
Unknown types render a safe generic activity row.

- [ ] **Step 4: Implement composer, controls, and reconnect**

Use one EventSource per selected Conversation. On open/reconnect, reload
Conversation, Timeline, and active Run projections. Never append replayed token
fragments. Use `reply_to_id` to resolve the correct attempt.

- [ ] **Step 5: Verify and commit**

Run Task 7 tests plus the workbench page test and `bun run typecheck`; commit
with `feat(web): render research conversation timeline`.

---

### Task 8: Unified Context Panel and report workflow

**Files:**
- Create: `web/src/components/ContextPanel.tsx`
- Create: `web/src/components/ContextPanel.test.tsx`
- Modify: `web/src/components/ConversationPanel.tsx`
- Modify: `web/src/pages/ConversationWorkbenchPage.tsx`
- Modify: `web/src/styles.css`

**Interfaces:**
- Produces one Context Panel for Run, SearchPlanVersion, Material, Evidence, Citation, ReportVersion, and error detail.

- [ ] **Step 1: Write failing Context Panel tests**

```tsx
await user.click(screen.getByRole("button", { name: "查看 Search Plan V4" }));
expect(api.searchPlanVersion).toHaveBeenCalledWith("plan-version-4");
await user.click(screen.getByRole("button", { name: "查看报告 V2" }));
expect(api.reportVersion).toHaveBeenCalledWith("report-2");
```

Also test focus transfer, Escape/close button, and mobile dialog behavior.

- [ ] **Step 2: Verify RED**

Run `bun run test -- src/components/ContextPanel.test.tsx` from `web/`.

- [ ] **Step 3: Implement typed Context selection**

```ts
type ContextSelection =
  | { kind: "run"; id: string }
  | { kind: "search_plan_version"; id: string }
  | { kind: "material"; id: string }
  | { kind: "evidence"; id: string }
  | { kind: "citation"; id: string }
  | { kind: "report_version"; id: string }
  | { kind: "error"; id: string };
```

Each branch loads its authoritative endpoint; Timeline copies are never used
as authoritative report or Evidence content.

- [ ] **Step 4: Complete layout and report actions**

Desktop uses list, flexible Timeline, and on-demand right panel. Below 800 px,
the sidebar becomes navigation and Context becomes a full-screen dialog. Report
cards show checkpoint/state version, Draft status, view, and publish actions.

- [ ] **Step 5: Verify and commit**

Run Task 8 and Timeline tests, `bun run check`, `bun run typecheck`, and
`bun run build`; commit with `feat(web): add unified research context panel`.

---

### Task 9: Recovery checks, end-to-end smoke test, and documentation

**Files:**
- Modify: `scripts/smoke_conversation.py`
- Modify: `tests/test_smoke_conversation.py`
- Create: `tests/test_conversation_recovery.py`
- Modify: `README.md`
- Modify: `docs/architecture/conversation-task-runtime-architecture.md`

**Interfaces:**
- Verifies the complete Conversation-first user path and crash boundaries.
- Documents only behavior that is actually implemented.

- [ ] **Step 1: Write the failing smoke and recovery tests**

The smoke path must create an INTAKE Conversation, answer a capability query
without a Task, create a Task and initial Run from a clear research request,
consume SSE by event sequence, read Timeline by timeline sequence, ask a
committed-evidence question, stop a running Run, open a stable Context object,
and create/publish a report version.

Recovery tests kill the runtime before and after a checkpoint transaction and
expire leases for RUNNING/STOPPING Runs. Assert committed state never contains
working assets, orphaned Runs become INTERRUPTED, and retry creates a linked
new Run.

- [ ] **Step 2: Verify RED**

Run:

```bash
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest \
  tests/test_smoke_conversation.py tests/test_conversation_recovery.py -q
```

- [ ] **Step 3: Implement the minimum smoke and recovery support**

Reuse the production repositories and FastAPI test client. Do not create a
parallel test-only runtime or duplicate state machine.

- [ ] **Step 4: Update operator and architecture documentation**

Document the Conversation-first entry point, capability-only INTAKE behavior,
Task creation boundary, Run stop/cancel/retry meanings, committed-evidence QA,
separate SSE/Timeline cursors, and stable Context links. Remove obsolete
instructions that tell users to start with the topic form.

- [ ] **Step 5: Run full verification**

```bash
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run ruff format --check .
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run ruff check .
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pyright
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv build
cd web
bun install --frozen-lockfile
bun run test
bun run check
bun run typecheck
bun run build
```

- [ ] **Step 6: Commit the verified delivery**

Commit with `docs: complete conversation-first workbench delivery` only after
all checks pass and `git status --short` contains no unintended files.
