# Conversation-First Research Workbench Design

| Item | Decision |
| --- | --- |
| Status | Architecture frozen; implementation planning pending written review |
| Date | 2026-08-25 |
| Parent architecture | `docs/architecture/conversational-research-task-architecture.md` |
| Deployment | Single machine, single user |
| Revision | Replaces the task-page-first interaction model with a conversation-first model |

## 1. Goal and boundaries

The Web application is a conversation workbench, not a research form with a
chat tab. A user creates a Conversation, states a research need in natural
language, observes research progress in the timeline, asks questions against
committed evidence, changes an active run at a safe checkpoint, and explicitly
publishes a versioned report.

The design preserves these boundaries:

- `IntelTask` is the durable research object; `Conversation` is an interaction
  context and may exist before a task;
- ordinary questions never start network activity;
- only checkpoint-committed assets can support evidence answers or reports;
- live progress explains current work but is not evidence;
- timeline entries are projections and never determine domain state;
- reports, SearchPlans, checkpoints, citations, and runs are opened by stable
  version or object ID;
- the first release has no accounts, roles, authentication, authorization,
  tenants, remote collaboration, Redis, Celery, or WebSocket;
- large source and report files remain on the filesystem with path-boundary and
  SHA-256 checks.

## 2. Selected architecture

The selected approach is a thin conversation intake layer over the existing
research and evidence runtimes:

```text
Conversation INTAKE
  → Intake Agent (no tools)
  → immutable ResearchBrief
  → atomic IntelTask + initial ResearchRun binding
  → Research Runtime
  → checkpoint committed state
  → Evidence QA / ReportVersion
```

A global chat orchestrator that can silently switch tasks is rejected because
it weakens task ownership and evidence isolation. A frontend-only chat wrapper
around the existing topic form is rejected because it cannot persist
clarification turns, recover processing, or represent a Conversation before a
Task exists.

## 3. Domain model

### 3.1 Conversation and IntelTask

The left navigation contains Conversations, never IntelTasks disguised as
conversations.

```text
Conversation
  id
  task_id nullable
  status = INTAKE | ACTIVE | ARCHIVED
  title
  active_epoch_id
  created_at
  updated_at
```

State invariants:

```text
INTAKE   → task_id may be NULL
ACTIVE   → task_id must not be NULL
ARCHIVED → task_id may be NULL or non-NULL
```

`Conversation.status` is independent of `IntelTask` and `ResearchRun` status.
Archiving a Conversation changes its visibility and context only; it never
stops or deletes research.

Relationship cardinality is:

```text
Conversation → 0..1 IntelTask
IntelTask    → 0..N Conversation
```

No unique constraint is placed on `Conversation.task_id`. Binding is immutable
once non-NULL. V1 does not expose “create another Conversation for this Task”
in the UI, but the schema does not make that future workflow a migration.

### 3.2 ResearchBrief

`ResearchBrief` is an immutable, versioned Pydantic value object and the input
contract for task creation:

```text
ResearchBrief
  schema_version
  topic
  objective
  key_questions[]
  scope
    time_range
    geography[]
    entities[]
  constraints[]
  requested_outputs[]
```

The trigger relation is protected by a database constraint:

```text
IntelTask.origin_message_id UNIQUE
ResearchBrief.trigger_message_id UNIQUE
```

One accepted user Message can therefore create at most one IntelTask even if
multiple workers race or the client retries.

Task identity, the immutable brief, task/conversation binding, run metadata,
and events are transactional SQLite records. Source bodies and extracted media
stay on the filesystem. Existing task JSON is imported into the SQLite task
registry before it can be bound; it is not dual-written after import.

### 3.3 Message and processing attempts

A submitted user Message is an immutable statement; model or runtime failure
does not make the user's statement itself “failed”.

```text
Message
  id
  conversation_id
  epoch_id
  message_sequence
  client_message_id nullable
  role = USER | ASSISTANT
  content
  reply_to_id nullable
  created_at
```

Processing is represented separately:

```text
MessageProcessingAttempt
  id
  user_message_id
  attempt
  status = ACCEPTED | PROCESSING | COMPLETED | FAILED | CANCELLED
  assistant_message_id nullable
  error_code nullable
  error_detail nullable
  started_at
  completed_at nullable
```

`(conversation_id, client_message_id)` is unique when the client ID is not
NULL. One user Message has at most one active processing attempt. Retrying a
failed processing attempt creates a new attempt; it does not duplicate or
rewrite the user's Message.

Assistant content is inserted as an immutable Message only after generation
completes. Partial tokens are transient and are not a durable Message.

### 3.4 ActionRequest and message intent

Messages received while research is running are classified as:

| Intent | Domain effect |
| --- | --- |
| `QUERY` | Answer from committed state; do not change a ResearchRun |
| `MODIFY` | Create an ActionRequest and apply it to the active run at a checkpoint |
| `CONTINUE` | After a terminal run, create exactly one new ResearchRun |
| `CONTROL` | Cancel a queued run/action or stop a running ResearchRun |

The same phrase can map differently by domain state: “continue checking Japan”
is `MODIFY` while a run is active and `CONTINUE` after the run is terminal.
`CONTINUE` never mutates an existing run.

### 3.5 ResearchRun

```text
ResearchRun
  id
  task_id
  action_request_id nullable
  continues_run_id nullable
  retry_of_run_id nullable
  input_committed_state_version
  active_search_plan_version_id
  status
  phase
  execution_owner_id nullable
  lease_expires_at nullable
  started_at nullable
  completed_at nullable
  error nullable
```

State machine:

```text
QUEUED ───────────────→ CANCELLED
  │
  └→ RUNNING ─────────→ SUCCEEDED
       ├───────────────→ FAILED
       ├───────────────→ INTERRUPTED
       └→ STOPPING ────→ STOPPED
```

`CANCEL` applies only to `QUEUED`. `STOP` applies only to `RUNNING` and first
commits `RUNNING → STOPPING`. Entering `STOPPING` prevents new work from being
scheduled and propagates cancellation. A component that cannot stop
immediately may return naturally, but its working output is discarded.

A checkpoint commit must verify that its run is still `RUNNING`. No checkpoint
can commit after `STOPPING` is visible.

At startup, `RUNNING` or `STOPPING` runs without a valid owner lease become
`INTERRUPTED` in a transaction with the corresponding durable event.
`INTERRUPTED` never returns to `RUNNING`. Retry creates a new run with
`retry_of_run_id`; user-authorized further research creates a new run with
`continues_run_id`.

### 3.6 ResearchCheckpoint and committed state

```text
working assets
  → ResearchCheckpoint transaction
  → committed assets
  → Evidence QA / Coverage / ReportVersion
```

Only a committed checkpoint advances `committed_state_version`. Query answers
and reports load committed asset IDs at one version. Search results, downloads,
OCR, transcription, candidate Facts, and candidate Evidence remain invisible
until checkpoint governance succeeds.

### 3.7 ReportVersion

Each report stores:

```text
based_on_checkpoint_id
based_on_committed_state_version
```

Both values are retained deliberately. Reads and publication verify that the
checkpoint's output state version equals the report's stored state version.

Publishing uses `BEGIN IMMEDIATE` and atomically verifies the Draft, validates
its checkpoint and hashes, supersedes the old Published version, publishes the
Draft, updates the IntelTask pointer, and appends `report.published`.

`report.created` is appended only in the transaction that successfully creates
a persistent ReportVersion. A generation start may be transient; it is never
named `report.created`.

## 4. Runtime components

### 4.1 Intake Agent

The Intake Agent has no search, fetch, filesystem, or research tools. It
returns strict structured data:

```text
intent = CAPABILITY_QUERY | CLARIFY_RESEARCH | START_RESEARCH
reply
research_brief nullable
missing_fields[]
```

Capability questions remain in `INTAKE` with `task_id=NULL`. An incomplete
research request receives a clarification question. A complete request creates
the Task and initial Run without a redundant confirmation.

### 4.2 Dialogue and research runtimes

The Dialogue Agent answers only from the current Task's committed assets and
has no network tools. The Research Runtime owns search, crawling, extraction,
Fact/Evidence governance, and checkpoints. They remain separate runtimes so a
normal question cannot accidentally trigger collection.

Two local model slots are preserved:

- user evidence/intake calls have interactive priority;
- research generations use the remaining capacity;
- an already-running generation is not preempted;
- simple state queries are answered without an LLM when possible.

### 4.3 RunStatusCard

The status card is a read-only projection:

```text
current phase and key question
live working batch and in-flight count
committed material/fact/evidence counts
covered key questions / total questions
active SearchPlanVersion ID
latest committed checkpoint ID
current gap or reason the run has not finished
```

Live counts explain what the system is doing. They never enter evidence
retrieval, Coverage, or reports.

### 4.4 Timeline and Context Panel

The information flow has three distinct layers:

```text
Domain State
  → Durable/Transient Events
  → TimelineEntry projection
```

Timeline entries cannot be used to determine whether a Run started, stopped,
or completed. Domain objects remain authoritative.

The right Context Panel opens stable IDs for:

```text
RUN_DETAIL
SEARCH_PLAN_VERSION
MATERIAL
EVIDENCE
CITATION
REPORT_VERSION
ERROR_DETAIL
```

Historical entries point to the exact SearchPlanVersion, checkpoint, citation,
or ReportVersion used at that time, not to a mutable “current” alias.

## 5. Persistence and event contract

### 5.1 Separate sequences

Durable events and timeline entries have independent monotonic sequences:

```text
DurableEvent
  event_sequence

TimelineEntry
  timeline_sequence
  source_event_id nullable
  source_event_sequence nullable
```

SSE `Last-Event-ID` always means `DurableEvent.event_sequence`.
Timeline `after_sequence` always means `TimelineEntry.timeline_sequence`.
The client must never compare or substitute the two values.

### 5.2 Transactional outbox

Every durable event that describes a domain transition is inserted in the same
SQLite transaction as that transition:

```text
BEGIN IMMEDIATE
update domain state
insert durable event/outbox row
commit
```

The SSE dispatcher reads committed outbox rows. It never manufactures durable
events after the domain transaction. Therefore neither “state committed but
event missing” nor “event visible but state rolled back” is allowed.

Transient `answer.delta`, fine-grained `run.progress`, and heartbeat events are
sent to connected clients and are not written to SQLite.

Timeline projection may lag durable events and can be rebuilt. Its rows retain
their source event relation when one exists.

## 6. API contract

Conversation is the primary API resource:

```text
POST /api/conversations
GET  /api/conversations
GET  /api/conversations/{conversation_id}
POST /api/conversations/{conversation_id}/archive

POST /api/conversations/{conversation_id}/messages
POST /api/messages/{message_id}/retry
GET  /api/conversations/{conversation_id}/timeline
GET  /api/conversations/{conversation_id}/events
```

Message submission returns HTTP 202 after the user Message, processing attempt,
and `message.accepted` outbox event commit. It accepts `client_message_id` and
uses the database uniqueness constraint for idempotency.

Run and action control targets domain objects:

```text
GET  /api/tasks/{task_id}/research-runs
GET  /api/research-runs/{run_id}
POST /api/research-runs/{run_id}/stop
POST /api/research-runs/{run_id}/cancel

POST /api/action-requests/{action_id}/confirm
POST /api/action-requests/{action_id}/reject
POST /api/action-requests/{action_id}/cancel
```

Context Panel reads use stable IDs:

```text
GET /api/research-runs/{run_id}/search-plan
GET /api/search-plan-versions/{version_id}
GET /api/documents/{document_id}
GET /api/evidence/{evidence_id}
GET /api/messages/{message_id}/citations
GET /api/report-versions/{report_version_id}
```

The active SearchPlan response includes both `active_version_id` and its
numeric version. Timeline history uses `/search-plan-versions/{version_id}`.

Legacy task-scoped conversation endpoints remain temporary compatibility
adapters but are not used by the new frontend. Conversation-first SSE exists
before task binding, eliminating the previous task/conversation initialization
404.

## 7. SSE and reconnect behavior

```text
GET /api/conversations/{conversation_id}/events
Last-Event-ID: <durable event sequence>
```

Durable event types include:

```text
message.accepted
intake.clarification
task.created
action.queued
run.queued
run.started
run.stopping
run.stopped
run.interrupted
run.completed
run.failed
checkpoint.committed
answer.completed
report.created
report.published
```

`answer.completed` includes both the assistant `message_id` and the triggering
`reply_to_id`, so replayed historical answers cannot satisfy the wrong request.

On reconnect the client:

1. replays durable events from `Last-Event-ID`;
2. does not request missing transient progress or token deltas;
3. reloads the Conversation, Timeline cursor, active Run, and selected Context
   Panel object from authoritative APIs;
4. replaces any partial answer placeholder with the complete Assistant Message
   after `answer.completed`.

## 8. Web interaction

The desktop page has three conceptual regions:

```text
Conversation list | Conversation timeline | Context Panel
```

The Context Panel is closed until the user opens a run, plan, material,
evidence, citation, report, or error. On mobile the list becomes navigation and
the Context Panel becomes a full-screen layer.

`/` opens the latest active Conversation or an empty welcome state. “New
conversation” creates an `INTAKE` Conversation; no topic form is shown. The
timeline renders Messages, clarification, run status cards, checkpoint cards,
errors, actions, and report version cards. The composer remains available while
research runs.

Historical task links open or lazily create a bound Conversation. The old
`/new` route redirects to a new Conversation. The old task detail page is no
longer part of the primary flow.

## 9. Error and recovery behavior

- Intake failure records a failed MessageProcessingAttempt and offers retry;
  the user Message remains immutable and the Conversation remains `INTAKE`.
- Task creation transaction failure creates no orphan Task, Run, binding, or
  durable event.
- Dialogue failure records a failed processing attempt and offers reprocessing.
- Checkpoint failure does not advance committed state or expose working assets.
- STOPPING honestly remains visible until cancellable work exits or
  non-cancellable output is discarded.
- Startup lease recovery marks abandoned RUNNING/STOPPING runs INTERRUPTED and
  writes the event in the same transaction.
- Interrupted runs do not auto-resume; Retry creates a new linked ResearchRun.
- Report generation failure creates no ReportVersion and no `report.created`.
- Report publication failure leaves the prior Published pointer unchanged.
- SSE disconnect rebuilds projections from durable outbox events and domain
  state, never from partial text.

## 10. Migration

The current feature implementation binds Conversation directly to an existing
Task and exposes task-scoped endpoints. The conversation-first migration:

1. stops all writers;
2. upgrades SQLite so `Conversation.task_id` is nullable and not unique;
3. adds ResearchBrief, MessageProcessingAttempt, task origin, lease, separate
   event/timeline sequences, and outbox constraints;
4. imports existing Task identity and status metadata into the SQLite task
   registry while retaining large research assets on the filesystem;
5. creates or lazily creates one bound Conversation for historical tasks;
6. switches the frontend to Conversation APIs;
7. keeps old task-scoped conversation routes only as compatibility adapters.

The migration is idempotent and leaves the old JSON metadata as a read-only
backup until integrity validation succeeds. There is no steady-state dual
write of task identity or lifecycle status.

## 11. Quantified acceptance

| Scenario | Acceptance criterion |
| --- | --- |
| Capability query | “What can you do?” creates no Task/Run and calls no search/fetch tool |
| Clear research request | One accepted trigger creates exactly one Task and one Initial Run |
| Intake idempotency | Ten concurrent retries of one client message still create one Message, Brief, Task, and Run |
| Conversation relation | Multiple Conversations may reference one Task; one Conversation cannot switch Tasks |
| Task isolation | 100% of citations, materials, evidence, actions, runs, and reports belong to the bound Task |
| Ordinary QA | Zero search, fetch, crawl, or continuation calls |
| Working boundary | Working assets remain invisible to QA and reports before checkpoint commit |
| STOP | After RUNNING→STOPPING commits, zero later checkpoints can commit for that Run |
| CANCEL | Only a QUEUED Run may transition to CANCELLED |
| CONTINUE | Each authorized continuation creates exactly one new linked ResearchRun |
| Event sequence | Last-Event-ID uses only event sequence; timeline cursor uses only timeline sequence |
| Event transaction | Fault injection never yields committed state without its durable event or an event for rolled-back state |
| SSE recovery | Reconnect from every durable sequence replays each later durable event once |
| Report consistency | Report checkpoint state version equals stored report state version in 100% of versions |
| Publication failure | Fault injection preserves the previous Published pointer and status |
| Historical Task | Repeated opening creates no duplicate bound Conversation |
| Conversation-first UI | Primary research flow never displays the topic form or requires the old task page |
| Static quality | Ruff, Pyright, frontend typecheck, Python build, and frontend build all pass |
| Automated behavior | Full pytest and frontend test suites pass |

Crash-recovery tests terminate the process before and after checkpoint
transactions and while a Run is RUNNING or STOPPING. After restart:

- committed state never moves backward or includes uncommitted assets;
- abandoned active runs become INTERRUPTED;
- no Task, Run, ReportVersion, or durable event is duplicated;
- retry produces a new auditable Run rather than resurrecting the old one.
