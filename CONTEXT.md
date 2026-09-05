# Research Agent

This context manages a loopable material-collection research system: it
searches for sources, fetches and extracts raw material, stores traceable
materials, and lets a research agent decide whether evidence is sufficient or
more research is needed (spec v0.1).

## Research flow

**ResearchTask**:
The durable unit of one research question, its round count, budget usage, and
checkpoint. `run` creates one; `resume` re-enters the same task without
resetting budget or deadline.
_Avoid_: Run, conversation turn

**ResearchDecision**:
The structured output the agent produces for a round: either `search` (with
queries) or `finish` (with a draft answer and citation ids). The orchestrator
validates it; the agent cannot raise its own budget or access storage.
_Avoid_: Tool call, hidden action

**ResearchOrchestrator**:
The deterministic state machine (PLAN → SEARCH → ACQUIRE → INDEX →
BUILD_CONTEXT → EVALUATE → CONTINUE/FINISH). It enforces rounds, budget, and
deadlines; the agent only decides.
_Avoid_: Agent loop, model-driven control flow

**ResearchResult**:
The final answer, resolvable citations, limitations, stop reason, and actual
usage. `completed` only when the flow finished normally and the agent decided
to finish.
_Avoid_: Report draft, chat answer

## Materials and identity

**Resource**:
An immutable byte blob, content-addressed by SHA-256. The same bytes may be
shared across origins, but each keeps its own resource record. Original and
derived files live on the filesystem; SQLite holds metadata.
_Avoid_: Document, search result

**DocumentIdentity** / **Revision**:
A source's stable identity (`source_key`) and one version of its raw content
(revision). Same source + same hash reuses the same revision.
_Avoid_: URL, mutable record

**Artifact**:
An immutable versioned extraction output, keyed by revision + extraction
profile + normalizer version + output manifest hash. Re-extraction with a new
backend produces a new artifact without rewriting cited ones.
_Avoid_: Editable document, mutable parse result

**EvidenceBlock**:
The authoritative body expression: ordered text blocks with a media-aware
`Locator` (page, slide, sheet, time range, region) and an origin method
(native text, OCR, subtitle, ASR). Text is derived from blocks, never edited
independently.
_Avoid_: Plain string body

**Chunk**:
A structure-first slice of an artifact for retrieval, carrying exact per-block
spans and locators. Re-chunking never silently replaces old references.
_Avoid_: Overlapping fragment, mutable slice

**Citation**:
A resolvable pointer from an answer back to a chunk, artifact, revision,
resource, and source location. Citation ids are stable within a context
package; model-emitted ids must exist in the mapping.
_Avoid_: Model-written source number, arbitrary URL

## Retrieval and context

**MaterialScope**:
A fixed set of artifacts for one context build, constrained by task first and
resolved once. All retrieval (direct / lexical / vector / hybrid) must recall
within this scope.
_Avoid_: Whole-library search

**ContextPackage**:
The token-bounded evidence text, selected chunks, citations, and coverage
summary passed to the agent for one decision. Its `max_tokens` is only the
evidence budget, already excluding system/task/history and reserved output.
_Avoid_: Raw concatenation, unbounded prompt

## Execution

**DomainError**:
The stable failure contract across services, carrying `code`, `stage`,
`message`, and retry semantics. Batch boundaries convert single-item errors
into reports and keep successful items.
_Avoid_: Wrapped exception with only a message
