# Public Information Research

This context manages task-scoped public-information research, the evidence
behind its conclusions, and the conversation through which a user observes or
extends that research.

## Research

**IntelTask**:
The durable investigation boundary that defines one topic, its questions, and
its scope. All runs, conversations, materials, evidence, and reports belong to
exactly one IntelTask.
_Avoid_: Job, chat, session

**IntelQuestion**:
A stable question within an IntelTask whose answerability and evidence coverage
can change as research continues.
_Avoid_: Prompt, query

**ResearchRun**:
One auditable attempt to advance an IntelTask from a frozen input state. An
IntelTask may have many ResearchRuns but at most one active ResearchRun.
_Avoid_: Task, conversation turn

**SearchPlanVersion**:
An immutable version of the planned questions, priorities, and retrieval
directions used by a ResearchRun.
_Avoid_: Current plan, mutable plan

**Checkpoint**:
The atomic boundary at which a ResearchRun makes newly governed assets visible
to task-level readers.
_Avoid_: Autosave, partial result

**Committed State**:
The task state visible to evidence question answering. In-progress candidates
are excluded until a Checkpoint commits them.
_Avoid_: Live working state

## Interaction

**Conversation**:
The single task-scoped interaction history through which a user asks about or
requests actions on an IntelTask. It does not own research assets.
_Avoid_: Research Agent, knowledge base

**ConversationEpoch**:
One visible context segment of a Conversation. Starting a new epoch archives
the previous visible context without deleting its audit history.
_Avoid_: New task, deleted chat

**Message**:
An immutable user or assistant utterance within a ConversationEpoch.
_Avoid_: Command, event

**DialogueIntent**:
The structured interpretation of what one user Message requests, independent
of whether that request is authorized to change task state.
_Avoid_: Keyword match, tool call

**ActionRequest**:
An immutable business request produced from a Message and advanced through an
explicit authorization and execution lifecycle.
_Avoid_: Direct tool call, hidden action

**TaskSnapshot**:
A rebuildable read-only projection of current task progress, gaps, assets, and
active work. It is never an authoritative source of state.
_Avoid_: Task record, durable truth

## Research Assets

**IntelDocument**:
An archived public source whose original and extracted content are integrity
checked and owned by one IntelTask.
_Avoid_: Evidence, search result

**Fact**:
A canonical atomic claim associated with one IntelQuestion. A Fact may be
accepted, disputed, rejected, or superseded without erasing its history.
_Avoid_: Document summary, report paragraph

**Evidence**:
An immutable exact passage from an IntelDocument linked to a Fact with a stated
supporting or contradicting relation.
_Avoid_: Material, source score

**SupportReview**:
An immutable semantic judgment about whether one Evidence passage supports its
linked Fact.
_Avoid_: User preference, reading recommendation

**ReportVersion**:
An immutable task report bound to the runs, facts, and evidence available when
it was generated. A task has at most one published ReportVersion.
_Avoid_: Mutable report, chat answer

**Reading Priority**:
A 1–5 recommendation describing how useful a material is to read for the task.
It does not express source credibility, factual truth, or evidence quality.
_Avoid_: Confidence score, trust rating
