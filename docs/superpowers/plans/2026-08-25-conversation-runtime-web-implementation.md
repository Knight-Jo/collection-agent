# Conversation Runtime and Web Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver task-scoped evidence chat, explicit same-task continued research, report version actions, durable FastAPI/SSE APIs, and a usable Web conversation tab.

**Architecture:** Add a SQLite-backed `ConversationRuntime` beside the initial-task `RunRegistry`. Read existing JSON research assets through a bounded lexical retriever, let a tool-free Dialogue Agent answer only from allow-listed passages, and run explicit continuations through the existing research Agent with a restricted tool capability. Keep existing research JSON authoritative while SQLite stores conversation state, committed asset IDs, citations, runs, checkpoints, report versions, and events.

**Tech Stack:** Python 3.12, stdlib SQLite/asyncio, Pydantic AI, FastAPI SSE, React 19, TypeScript, Bun/Vitest.

**Spec:** `docs/superpowers/specs/2026-08-25-conversation-runtime-web-design.md`

**Delivery status (2026-08-25):** Complete. Backend formatting, lint, type checks,
full pytest suite and package build passed; frontend install, tests, Biome check,
TypeScript check and production build passed. The deterministic HTTP/SSE smoke
harness also passed its focused tests.

## Global Constraints

- Single machine and single user; add no account, role, authentication, authorization, tenant, or collaboration fields.
- Normal questions never invoke search, fetch, crawl, or the continuation runner.
- Every retrieved passage, citation, action, run, and report is checked against the current `task_id`.
- SQLite stays at `data/intel/intel.db` in WAL mode; existing research records remain JSON/filesystem records.
- Dialogue context is bounded to one task snapshot, epoch summary, ten recent messages, and eight passages.
- Persist durable SSE events only; do not persist token deltas or heartbeat events.
- Use the existing OpenAI-compatible model configuration and two-slot local deployment; add no model provider dependency.
- Every behavior change follows RED → GREEN → focused regression → commit.

---

### Task 1: SQLite schema v2 and citation/asset models

**Files:**
- Modify: `src/intel_agent/models.py`
- Modify: `src/intel_agent/state_db.py`
- Modify: `tests/test_state_models.py`
- Modify: `tests/test_state_db.py`

**Interfaces:**
- Produces: `MessageCitation`, `CitationDraft`, `CommittedAssetType`.
- Produces schema tables: `message_citations`, `task_committed_assets`, `checkpoint_assets`.
- Produces schema version 2 migration on both fresh and existing version 1 databases.

- [x] **Step 1: Write failing model and migration tests**

Add tests that construct a line-based citation, reject `line_end < line_start`, initialize a fresh database, and upgrade a copied version 1 database. Assert schema versions are `[1, 2]`, citation sequence is unique per message, and committed asset identity is unique per task/type/ID.

- [x] **Step 2: Run focused tests and verify RED**

Run:

```bash
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest tests/test_state_models.py tests/test_state_db.py -q
```

Expected: imports/tables for citation and committed assets are missing.

- [x] **Step 3: Implement models and explicit v2 migration**

Add:

```python
CommittedAssetType = Literal["document", "fact", "evidence"]


class CitationDraft(BaseModel):
    citation_kind: Literal["verified_evidence", "material_clue"]
    document_id: str
    evidence_id: str | None = None
    fact_id: str | None = None
    title: str
    source_url: str
    quote_text: str
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    source_content_hash: str


class MessageCitation(CitationDraft):
    id: str
    task_id: str
    message_id: str
    sequence: int = Field(ge=1)
    created_at: str
```

Validate the line range after model construction. Keep the current schema as version 1 and apply a separate idempotent `SCHEMA_V2` only when migration 2 is absent.

- [x] **Step 4: Run focused tests and verify GREEN**

Run the Task 1 test command again; expected all pass.

- [x] **Step 5: Commit**

```bash
git add src/intel_agent/models.py src/intel_agent/state_db.py tests/test_state_models.py tests/test_state_db.py
git commit -m "feat(conversation): add citation schema"
```

### Task 2: Atomic conversation projection and committed assets

**Files:**
- Modify: `src/intel_agent/state_store.py`
- Modify: `tests/test_state_store.py`

**Interfaces:**
- Produces: `seed_committed_assets(task_id, assets)`.
- Produces: `committed_asset_ids(task_id, asset_type)`.
- Produces: `set_message_processing(message_id)` and `fail_message(message_id, error)`.
- Extends: `complete_message(user_message_id, content, citations=())`.
- Produces: `citations_for_message`, `list_actions`, `get_action`, `list_runs`, `get_run`, and `list_reports`.
- Makes message acceptance/completion events part of the same transaction.

- [x] **Step 1: Write failing transactional tests**

Cover baseline seeding idempotency, citation insertion with assistant completion, cross-task citation rejection, `message.accepted`/`answer.completed` event creation, processing/failure transitions, and list projections ordered by stable sequence/version.

- [x] **Step 2: Run tests and verify RED**

```bash
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest tests/test_state_store.py -q
```

Expected: the new repository methods and citation parameter are missing.

- [x] **Step 3: Implement short SQLite transactions**

Use `BEGIN IMMEDIATE` only for sequence allocation and multi-record state changes. `complete_message` validates every `CitationDraft` against the supplied task, inserts assistant message/citations/event, and completes the user message in one commit. Repository read methods return Pydantic objects, never `sqlite3.Row`.

- [x] **Step 4: Run repository/storage regression tests**

```bash
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest tests/test_state_store.py tests/test_state_db.py tests/test_storage.py -q
```

- [x] **Step 5: Commit**

```bash
git add src/intel_agent/state_store.py tests/test_state_store.py
git commit -m "feat(conversation): persist projections and citations"
```

### Task 3: Task-scoped lexical retrieval

**Files:**
- Create: `src/intel_agent/retrieval.py`
- Create: `tests/test_retrieval.py`

**Interfaces:**
- Produces: `RetrievedPassage`.
- Produces: `TaskRetriever(cwd, store).seed_completed_task(task_id)`.
- Produces: `TaskRetriever.retrieve(task_id, query, *, limit=8, snapshot=None)`.

- [x] **Step 1: Write failing retrieval tests**

Build real temporary task/document/fact/evidence fixtures. Verify query terms rank the matching verified Evidence first, material text can return a clue, uncommitted/cross-task asset IDs are excluded, line/hash metadata is correct, and document tampering raises the existing integrity error.

- [x] **Step 2: Run tests and verify RED**

```bash
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest tests/test_retrieval.py -q
```

Expected: `intel_agent.retrieval` does not exist.

- [x] **Step 3: Implement bounded lexical retrieval**

Reuse `tokenize_query`, `get_task_view`, `load_document`, and `verify_document_integrity`. Score token overlap across question, Fact, quote, and title. Scan only committed documents, at most 200,000 characters per document, in twelve-line chunks. Return verified Evidence before equally scored material clues and cap output at `limit`.

- [x] **Step 4: Verify GREEN and regression**

Run retrieval, evidence, and Web view tests.

- [x] **Step 5: Commit**

```bash
git add src/intel_agent/retrieval.py tests/test_retrieval.py
git commit -m "feat(conversation): retrieve task evidence"
```

### Task 4: Tool-free Dialogue Agent and bounded context

**Files:**
- Create: `src/intel_agent/dialogue.py`
- Create: `tests/test_dialogue.py`

**Interfaces:**
- Produces: `DialogueDecision`, `DialogueAction`, `DialogueEngine`.
- Produces: `build_dialogue_prompt(task, summary, messages, passages, run_status)`.
- Produces: `DialogueEngine.answer(...)` and `DialogueEngine.summarize(...)`.

- [x] **Step 1: Write failing parser/prompt tests**

Use a fake Pydantic Agent result. Verify malformed/non-object JSON is rejected, cited passage IDs outside the provided allow-list are removed, ordinary evidence questions cannot acquire an action absent model output, explicit/proposed action modes validate, and prompt size/content excludes unrelated task material.

- [x] **Step 2: Verify RED**

```bash
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest tests/test_dialogue.py -q
```

- [x] **Step 3: Implement one-call JSON dialogue**

Create an Agent with the configured OpenAI-compatible chat model, no tools, the existing thinking setting, and at most `min(main_output_tokens, 2048)` output tokens. Parse fenced or plain JSON once; on failure issue one repair prompt, then raise `IntelError("DIALOGUE_FAILED", ...)`. Validate citations against `RetrievedPassage.id` in server code.

- [x] **Step 4: Verify GREEN**

Run dialogue and context tests.

- [x] **Step 5: Commit**

```bash
git add src/intel_agent/dialogue.py tests/test_dialogue.py
git commit -m "feat(conversation): add evidence dialogue agent"
```

### Task 5: Conversation runtime and recovery

**Files:**
- Create: `src/intel_agent/conversation.py`
- Create: `tests/test_conversation.py`

**Interfaces:**
- Produces: `ConversationRuntime(cwd, settings, *, dialogue, retriever, continuation, publisher)`.
- Produces: `submit_message`, `wait_message`, `confirm_action`, `reject_action`, `cancel_message`, and `recover`.
- Produces: `conversation_view(task_id)` dictionary consumed by Web schemas.

- [x] **Step 1: Write failing runtime tests**

Use fake dialogue/retrieval implementations. Verify async acceptance and completion, exact retry idempotency, citation binding, proposed versus explicit actions, model failure status, restart recovery, epoch summary update after twelve unsummarized messages, and no continuation call for ordinary questions.

- [x] **Step 2: Verify RED**

```bash
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest tests/test_conversation.py -q
```

- [x] **Step 3: Implement the minimal async runtime**

Use one `asyncio.Lock` for dialogue generations and a task dictionary keyed by user message ID. Persist before scheduling. Recovery reschedules user messages lacking a reply. Build `CitationDraft` only from the server passage objects selected by the validated decision. Summary failure is logged and does not fail the answer.

- [x] **Step 4: Verify GREEN**

Run conversation, dialogue, retrieval, and state-store tests.

- [x] **Step 5: Commit**

```bash
git add src/intel_agent/conversation.py tests/test_conversation.py
git commit -m "feat(conversation): process persistent task dialogue"
```

### Task 6: Restricted same-task continuation and shared research gate

**Files:**
- Modify: `src/intel_agent/agent.py`
- Modify: `src/intel_agent/task.py`
- Create: `src/intel_agent/continuation.py`
- Modify: `src/intel_agent/web/runs.py`
- Create: `tests/test_continuation.py`
- Modify: `tests/test_web_runs.py`

**Interfaces:**
- Produces: `ResearchGate` with one active research execution.
- Produces: `ContinuationRunner.run(action, cancellation_token)`.
- Extends: `build_agent(..., system_prompt=SYSTEM_PROMPT, allowed_tools=None)`.
- Produces: `activate_task(cwd, task_id)`.

- [x] **Step 1: Write failing restricted-run tests**

Capture model request tool definitions and assert forbidden task/report tools are absent. Verify the requested task becomes active, ordinary RunRegistry and continuation share one gate, continuation records run/action transitions, success commits new asset IDs/checkpoint version, failure leaves the prior allow-list unchanged, and cancel marks the run/action terminal.

- [x] **Step 2: Verify RED**

```bash
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest tests/test_continuation.py tests/test_web_runs.py -q
```

- [x] **Step 3: Implement restricted execution**

Filter `ModelRequestParameters.function_tools` in a small Pydantic AI capability using `dataclasses.replace`. Run the Agent once with the continuation prompt and existing `AgentDeps`. Snapshot committed IDs before execution, diff verified task-owned IDs after success, then bind new IDs during checkpoint commit.

Before the call, save the Task's search/fetch budget counters and temporarily
reset those counters on the active Task so a completed task can collect again.
In `finally`, restore the saved budget counters while retaining the latest
`evidence_count`. Do not expose task planning, report generation, or stage
tools.

- [x] **Step 4: Verify GREEN and core-agent regressions**

Run continuation, runner, deep-crawl workflow, and Web run tests.

- [x] **Step 5: Commit**

```bash
git add src/intel_agent/agent.py src/intel_agent/task.py src/intel_agent/continuation.py src/intel_agent/web/runs.py tests/test_continuation.py tests/test_web_runs.py
git commit -m "feat(conversation): continue research in task"
```

### Task 7: Report drafts without implicit publication

**Files:**
- Modify: `src/intel_agent/report.py`
- Create: `src/intel_agent/report_versions.py`
- Modify: `src/intel_agent/conversation.py`
- Create: `tests/test_report_versions.py`

**Interfaces:**
- Produces: `render_verified_report(cwd, task_id, *, allowed_fact_ids)` without changing Task outputs.
- Produces: `ReportPublisher.create_draft(task_id)` and `publish(report_id, ...)`.

- [x] **Step 1: Write failing report-version tests**

Verify draft creation preserves the legacy published binding, filters uncommitted Fact IDs, writes a hash-verified file, abandons an older draft, publishes atomically, supersedes the prior publication, and enforces stale-state confirmation.

- [x] **Step 2: Verify RED**

```bash
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest tests/test_report_versions.py -q
```

- [x] **Step 3: Extract rendering and implement publisher**

Reuse current report validation/citation rendering. Separate content rendering from `bind_task_output`; retain `generate_research_report` behavior by calling both. The new publisher writes `output/report-versions/{report_id}.md`, verifies SHA-256, and records the draft in `StateStore`.

- [x] **Step 4: Verify GREEN and report regressions**

Run report-version and existing report tests.

- [x] **Step 5: Commit**

```bash
git add src/intel_agent/report.py src/intel_agent/report_versions.py src/intel_agent/conversation.py tests/test_report_versions.py
git commit -m "feat(conversation): version task reports"
```

### Task 8: FastAPI conversation, action, report, and SSE contract

**Files:**
- Modify: `src/intel_agent/web/schemas.py`
- Create: `src/intel_agent/web/conversation.py`
- Modify: `src/intel_agent/web/app.py`
- Modify: `src/intel_agent/web/views.py`
- Create: `tests/test_web_conversation.py`

**Interfaces:**
- Produces every HTTP/SSE endpoint listed in the design specification.
- Extends `create_app` with injectable `conversation_runtime` and shared `research_gate`.

- [x] **Step 1: Write failing API contract tests**

Verify conversation GET, message POST 202/idempotency, message GET/cancel, action confirm/reject/cancel, run list/cancel, report list/create/publish, stable error codes, task ownership rejection, durable SSE sequence replay, and heartbeat format. Use fake runtime/runner dependencies; make no model/network calls.

- [x] **Step 2: Verify RED**

```bash
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest tests/test_web_conversation.py -q
```

- [x] **Step 3: Implement schemas/router and app wiring**

Put route handlers in `web/conversation.py` and include the router from `create_app`; keep `app.py` as composition root. Start recovery lazily on first conversation operation. Map conflict/stale/dialogue errors to 409/503 without exposing tracebacks. Use SQLite event sequence for SSE `id`, named `event`, JSON `data`, and fifteen-second comment heartbeats.

- [x] **Step 4: Verify GREEN and all Web API regressions**

Run `tests/test_web_conversation.py`, `tests/test_web_api.py`, `tests/test_web_runs.py`, and `tests/test_web_views.py`.

- [x] **Step 5: Commit**

```bash
git add src/intel_agent/web/schemas.py src/intel_agent/web/conversation.py src/intel_agent/web/app.py src/intel_agent/web/views.py tests/test_web_conversation.py
git commit -m "feat(web): expose persistent task conversation"
```

### Task 9: React conversation tab

**Files:**
- Create: `web/src/components/ConversationPanel.tsx`
- Create: `web/src/components/ConversationPanel.test.tsx`
- Modify: `web/src/pages/TaskPage.tsx`
- Modify: `web/src/pages/TaskPage.test.tsx`
- Modify: `web/src/api.ts`
- Modify: `web/src/types.ts`
- Modify: `web/src/styles.css`

**Interfaces:**
- Produces a complete task conversation UI and typed API client.

- [x] **Step 1: Write failing component tests**

Test empty/loading/error states, sending with a generated client UUID, pending placeholder, completed answer, citation expansion, proposal confirm/reject, active run cancellation, SSE-triggered refresh, reconnect indicator, draft creation, and publication.

- [x] **Step 2: Verify RED**

```bash
cd web && bun run test ConversationPanel TaskPage
```

Expected: the component/types/API methods do not exist.

- [x] **Step 3: Implement the conversation panel**

Add a third `dialogue` tab. Fetch the conversation projection on mount, create one `EventSource`, register durable event types to refresh, and close it on unmount. Render numbered citations as accessible buttons with expandable cards. Disable only state-changing controls while their request is pending; status and existing messages remain readable.

- [x] **Step 4: Verify GREEN and frontend quality**

```bash
cd web
bun run test
bun run typecheck
bun run build
```

- [x] **Step 5: Commit**

```bash
git add web/src/components/ConversationPanel.tsx web/src/components/ConversationPanel.test.tsx web/src/pages/TaskPage.tsx web/src/pages/TaskPage.test.tsx web/src/api.ts web/src/types.ts web/src/styles.css
git commit -m "feat(web): add task conversation workbench"
```

### Task 10: Documentation, full verification, and smoke harness

**Files:**
- Modify: `README.md`
- Modify: `docs/architecture/conversational-research-task-architecture.md`
- Modify: `docs/superpowers/plans/2026-08-25-conversation-runtime-web-implementation.md`
- Create: `scripts/smoke_conversation.py`
- Create: `tests/test_smoke_conversation.py`

**Interfaces:**
- Documents operation and provides an optional real-model conversation smoke command.

- [x] **Step 1: Write the smoke harness test first**

Test argument parsing and a fake API sequence: load task, post question, consume completion event, fetch answer/citation, optionally confirm a proposed continuation, and print stable JSON metrics.

- [x] **Step 2: Verify RED, implement harness, and verify GREEN**

Run `pytest tests/test_smoke_conversation.py -q`, implement the minimal HTTP client with stdlib `urllib`, then rerun.

- [x] **Step 3: Update usage documentation and mark this plan complete**

Document starting the workbench, opening a completed task's 对话 tab, normal evidence questions, explicit continuation, proposal confirmation, cancellation, draft generation/publication, and the smoke command. Record that accounts/roles remain out of scope.

- [x] **Step 4: Run full project verification**

```bash
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run ruff format --check .
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run ruff check .
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pyright
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv build
cd web
bun install --frozen-lockfile
bun run test
bun run typecheck
bun run build
```

- [x] **Step 5: Commit**

```bash
git add README.md docs/architecture/conversational-research-task-architecture.md docs/superpowers/plans/2026-08-25-conversation-runtime-web-implementation.md scripts/smoke_conversation.py tests/test_smoke_conversation.py
git commit -m "docs: complete conversation workbench delivery"
```
