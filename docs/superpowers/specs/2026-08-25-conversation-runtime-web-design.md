# Conversation Runtime and Web Workbench Design

| Item | Decision |
| --- | --- |
| Status | Approved for implementation |
| Date | 2026-08-25 |
| Parent architecture | `docs/architecture/conversational-research-task-architecture.md` |
| Deployment | Single machine, single user |

## 1. Goal

Turn the existing task report page into a complete task-scoped conversation
workflow. A user can ask questions about collected material, inspect precise
citations, explicitly continue research in the same task, observe that run,
generate a report draft, and publish a selected report version.

The delivery must preserve these boundaries:

- normal questions never start network activity;
- every answer and action belongs to the current `IntelTask`;
- only committed research state is visible to evidence answers;
- continued research never silently replaces the published report;
- the first release has no accounts, roles, authentication, authorization,
  tenants, or remote collaboration;
- existing Task, Document, Fact, Evidence, Coverage, and report bindings stay
  in their current JSON/filesystem stores until the separate offline migration.

## 2. Selected approach

Add a `ConversationRuntime` beside the existing `RunRegistry`. It owns message
processing and delegates three distinct operations:

1. `TaskRetriever` selects task-owned Evidence and material passages.
2. `DialogueEngine` performs one bounded model call for intent and answer.
3. `ContinuationRunner` performs an explicitly requested research extension
   with a restricted set of the existing research tools.

The existing `RunRegistry` remains responsible for initial research tasks.
It is not reused as a chat engine because an initial run assumes task creation,
full stage progression, and automatic report generation. The conversation
runtime instead records its own persistent `ResearchRun` and `ActionRequest`
state through `StateStore`.

## 3. Components

### 3.1 TaskRetriever

`TaskRetriever` reads only one supplied `task_id` and returns a bounded list of
server-created passages.

Retrieval order is:

1. accepted support Evidence and its Fact statement;
2. contradictory or disputed Evidence;
3. extracted task documents not represented in verified Evidence.

The first release uses the existing `tokenize_query` lexical tokens. Evidence
is scored against the question, Fact statement, quote, document title, and task
question. Material documents are scanned in bounded chunks and ranked by token
overlap. No embedding library or vector database is added.

Each passage carries:

```text
kind = VERIFIED_EVIDENCE | MATERIAL_CLUE
task_id
document_id
evidence_id?
fact_id?
title
source_url
quote
line_start
line_end
source_content_hash
```

Evidence is loaded through the existing integrity-verifying functions.
Document passages are read only after document hash verification. Retrieval
rejects cross-task references before they reach the model.

While a continuation run is active, retrieval is limited to the evidence and
document IDs captured in that run's input snapshot. New JSON records become
visible only after the final checkpoint commits and advances
`committed_state_version`.

Because research metadata has not yet migrated from JSON, SQLite also stores a
committed asset allow-list containing IDs and versions, not duplicate asset
records. Opening a completed legacy task seeds its current Document, Fact, and
Evidence IDs at version 0. Continuation output IDs join that allow-list only in
the final checkpoint transaction. A failed run may leave recoverable JSON
orphans, but retrieval and report generation exclude them. During an initial
research run that predates checkpoint integration, the conversation endpoint
offers status only; evidence Q&A becomes available when that run is terminal
and the baseline is seeded.

### 3.2 DialogueEngine

`DialogueEngine` is a separate Pydantic AI agent with no network or filesystem
tools. It receives:

```text
system instructions
+ compact task snapshot
+ active epoch summary
+ ten most recent messages
+ up to eight retrieved passages
+ current action/run status
```

The model returns plain JSON because current thinking-mode OpenAI-compatible
providers do not consistently support structured-output tool calls. The server
parses that JSON into a strict Pydantic model:

```text
intent
answer
answerability
cited_passage_ids[]
gaps[]
action?
  type
  request_mode = explicit_message | proposed
  scope
```

The server accepts citation IDs only when they are present in the retrieved
passage set. It creates citation records and assigns display sequence numbers;
the model cannot create URLs, line locations, document IDs, or citation
numbers.

An explicit imperative such as “继续搜索美国监管文件” may return
`explicit_message` and queue immediately. Questions, hypotheticals, negations,
and ambiguous requests may only return a proposal. The server never treats an
ordinary evidence question as permission to search.

### 3.3 ConversationRuntime

`ConversationRuntime` provides asynchronous processing around `StateStore`.
It owns one in-memory worker task per accepted user message but all durable
state is written before an HTTP response is returned.

Message flow:

```text
accept user Message + message.accepted
→ processing
→ retrieve task passages
→ DialogueEngine
→ bind MessageCitation records
→ insert complete assistant Message
→ create/queue ActionRequest when present
→ answer.completed and action.* durable events
```

The HTTP request returns `202 Accepted` after persistence. The browser receives
completion through task conversation SSE. Token deltas are not persisted and
are not required in this delivery; the UI displays a generating placeholder
and replaces it with the complete assistant message.

On application startup, the runtime scans accepted/processing user messages
without an assistant reply and schedules them again. Message idempotency and an
immutable assistant reply prevent duplicate answers after recovery.

After an epoch has more than twelve completed messages beyond
`summary_through_sequence`, the dialogue engine produces a background summary
through the last message before the four most recent exchanges. Updating the
summary and its covered sequence is atomic. Summary failure does not fail the
user's answer; the runtime keeps the older summary and relies on recent
messages.

### 3.4 ContinuationRunner

The continuation runner activates the requested existing task and runs the
current research Agent once with a continuation-specific system prompt. A
capability filters the exposed tools to:

```text
web_search, github_search, academic_search, news_search,
crawl_collect, web_fetch, document_search, document_read,
fact_save, fact_supersede, evidence_save, evidence_audit,
evidence_conflict_create, evidence_conflict_resolve, coverage_eval
```

It does not expose `intel_plan`, `material_digest`,
`generate_research_report`, or `intel_status`; continued research therefore
cannot create another task, advance the task to done, or replace a report.

Execution flow is:

```text
ActionRequest QUEUED
→ ResearchRun QUEUED/RUNNING
→ capture committed input snapshot
→ restricted continuation Agent
→ final ResearchCheckpoint commit
→ ResearchRun and ActionRequest SUCCEEDED
```

Failures mark the run and action failed and preserve the prior committed
allow-list. Uncommitted JSON output is not exposed as evidence and may be
adopted only by a later successful checkpoint or removed by maintenance.
Cancellation uses the existing Pydantic AI cancellation token. The first
release allows only one active initial or continuation research run in the
workspace.

One shared `ResearchGate` permits one initial or continuation research run in
the workspace. `RunRegistry` acquires it for initial tasks;
`ConversationRuntime` leaves a continuation queued until it can acquire the
same gate. The shared model scheduler has two slots. A research run holds one
slot; the dialogue runtime serializes user model calls through the other slot.
This matches the local two-slot deployment without adding a third worker or
preempting an active generation.

### 3.5 Report actions

`GENERATE_REPORT` and `REGENERATE_REPORT` are explicit actions. The report
publisher reuses the existing verification and rendering rules but writes the
result without changing the legacy Task output binding. It filters Fact and
Evidence through the committed allow-list, then stores the produced file as a
new `ReportVersion(DRAFT)` tied to the current committed state.

Publishing is a separate HTTP action. A current-state draft publishes
atomically; the prior published version becomes superseded. Publishing a stale
draft requires `publish_stale=true` and an exact current committed version. The
artifact read endpoint returns the published SQLite report when present and
falls back to the legacy Task report binding for unmigrated tasks.

## 4. Persistence changes

SQLite schema version 2 adds `message_citations`, `task_committed_assets`, and
`checkpoint_assets`. Initialization applies an explicit version 1 to version 2
migration rather than relying on `CREATE TABLE IF NOT EXISTS` to mutate an
existing database.

`message_citations` contains:

```text
id
task_id
message_id
sequence
citation_kind
document_id
evidence_id?
fact_id?
title
source_url
quote_text
line_start
line_end
source_content_hash
created_at
```

Constraints enforce unique `(message_id, sequence)` and one citation per
`(message_id, citation_kind, document_id, line_start, line_end)`. JSON-owned
document/evidence IDs are stored as immutable external identifiers after
server-side ownership and hash validation; they cannot be SQLite foreign keys
until the offline research-metadata migration.

`task_committed_assets` uniquely records `(task_id, asset_type, asset_id)` plus
the committed version. `checkpoint_assets` records which new IDs entered the
allow-list through each committed checkpoint. They contain no copied Fact,
Evidence, or Document content.

`StateStore` gains atomic methods for:

- accepting a message and appending `message.accepted`;
- changing a user message to processing/failed/cancelled;
- completing a reply together with citations and `answer.completed`;
- listing a conversation with actions, runs, reports, and citations;
- listing and cancelling task runs;
- creating and reading report versions.

No existing JSON record type is copied into SQLite in this delivery, so no
record is dual-written.

## 5. FastAPI contract

The application creates one `ConversationRuntime` and one shared model
scheduler. Tests may inject fake dialogue and continuation implementations.

```text
GET  /api/tasks/{task_id}/conversation
POST /api/tasks/{task_id}/conversation/messages
GET  /api/messages/{message_id}
POST /api/messages/{message_id}/cancel

POST /api/action-requests/{action_id}/confirm
POST /api/action-requests/{action_id}/reject
POST /api/action-requests/{action_id}/cancel

GET  /api/tasks/{task_id}/research-runs
POST /api/research-runs/{run_id}/cancel

GET  /api/tasks/{task_id}/report-versions
POST /api/tasks/{task_id}/report-versions
POST /api/report-versions/{report_id}/publish

GET  /api/tasks/{task_id}/conversation/events
```

Message creation accepts:

```json
{
  "content": "目前有哪些已确认结论？",
  "client_message_id": "browser-generated-uuid"
}
```

Proposal confirmation accepts a new `client_message_id`; the server writes a
visible confirmation user message and queues the unchanged action payload in
one operation. There is no identity or permission field in any request.

SSE uses durable conversation event sequence as its `id` and supports
`Last-Event-ID`. Heartbeats remain comments. Reconnect never appends partial
text; `answer.completed` causes the client to reload the full message.

## 6. Web interaction

The task page keeps the existing report and source tabs and adds a third
“对话” tab. It contains:

- chronological user and assistant messages;
- an input textarea and send button;
- a generating placeholder for accepted/processing messages;
- numbered citation buttons and expandable citation cards;
- evidence/material status, source title, URL, and exact line range;
- gap text and proposed action cards with confirm/reject buttons;
- current continuation run phase and cancel button;
- report draft list with publish action.

The page opens one `EventSource` while the conversation tab is mounted. On a
durable event it refreshes only the conversation projection. A disconnect
shows reconnecting state; the browser automatically reconnects and supplies
the last event ID.

The interface remains responsive down to 320 px. On narrow screens citation
cards render below the selected message instead of in a fixed side panel.

## 7. Error and recovery behavior

- model unavailable: message becomes failed and the UI offers retry with a new
  client message ID;
- no relevant evidence: assistant states the limitation and may propose a
  bounded search action;
- malformed model JSON: one repair attempt, then stable `DIALOGUE_FAILED`;
- stale proposal: action becomes expired instead of starting duplicate work;
- research already active: action stays queued until the current run ends;
- SSE disconnect: durable events replay; final assistant content is fetched
  from SQLite;
- process restart: unfinished messages are rescheduled and queued runs remain
  visible; a run that was running becomes interrupted and may be retried as a
  new run;
- cross-task message, citation, action, run, or report IDs are rejected.

## 8. Verification and acceptance

Backend tests use real temporary SQLite/JSON workspaces and fake model runners.
They verify:

- message persistence, idempotency, recovery, and task isolation;
- lexical retrieval and document integrity enforcement;
- model citation allow-list validation;
- explicit versus proposed search behavior;
- same-task continuation with restricted tools and checkpoint visibility;
- report draft/publish version rules;
- SSE replay and heartbeat behavior;
- cancellation and restart transitions.

Frontend tests verify sending, pending state, citation expansion, proposal
confirmation, run status, cancellation, reconnect refresh, and report draft
publishing. Final verification runs Ruff, Pyright, all pytest tests, Python
build, Bun tests, Bun typecheck, and Bun production build.

An optional real-model smoke test creates or opens one local task, asks one
evidence question, verifies at least one bound citation when evidence exists,
and issues one explicit bounded continuation request. External search quality
is reported separately from deterministic software acceptance.
