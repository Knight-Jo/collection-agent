# Context Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the research agent inside configurable 32K, 64K, 128K, or 256K context windows while preserving durable research state.

**Architecture:** Add one bounded context configuration, use Pydantic AI's native history processor to retain the initial task and recent complete exchanges, and reload a compact snapshot from existing JSON state. Bound model output and large tool returns at their existing shared entry points.

**Tech Stack:** Python 3.12, Pydantic, Pydantic AI, pytest.

**Spec:** `docs/superpowers/specs/2026-08-20-context-management-design.md`

**Status:** Implemented and verified on 2026-08-20. Automated checks passed;
the 32K Qwen3.5-9B recovery run reached `done/with_gaps` and generated the
formal report. The implementation also added stage-aware continuation and a
small-model-friendly report input discovered during the real run.

## Global Constraints

- Supported context windows are exactly 32768, 65536, 131072, and 262144 tokens.
- No new runtime service, database, tokenizer, or summarization model.
- Existing raw documents and evidence remain unchanged on disk.
- Comments and public docstrings are written in English.

---

### Task 1: Context configuration

**Files:**
- Modify: `src/intel_agent/config.py`
- Modify: `config.example.yaml`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `ContextConfig.history_max_bytes()` and `ContextConfig.tool_content_max_bytes()`.

- [ ] Add parameterized failing tests for all four supported windows, derived budgets, and rejection of unsupported windows.
- [ ] Run `uv run pytest tests/test_config.py -q` and verify RED.
- [ ] Implement `ContextConfig` and add it to `Settings`.
- [ ] Run `uv run pytest tests/test_config.py -q` and verify GREEN.

### Task 2: History compaction and state restoration

**Files:**
- Create: `src/intel_agent/context.py`
- Create: `tests/test_context.py`
- Modify: `src/intel_agent/agent.py`

**Interfaces:**
- Produces: `build_context_snapshot(cwd: Path) -> str` and `make_history_processor(config: ContextConfig)`.
- Consumes: existing task, fact, and coverage stores.

- [ ] Add failing tests proving the initial request and latest complete exchange survive while old exchanges are removed under the configured byte limit.
- [ ] Add a failing test proving the persisted task/fact/coverage snapshot is inserted without an LLM call.
- [ ] Run `uv run pytest tests/test_context.py -q` and verify RED.
- [ ] Implement the deterministic processor with `dataclasses.replace` and `ModelMessagesTypeAdapter`.
- [ ] Attach it using `ProcessHistory` in `build_agent`.
- [ ] Run `uv run pytest tests/test_context.py -q` and verify GREEN.

### Task 3: Output and tool-result bounds

**Files:**
- Modify: `src/intel_agent/agent.py`
- Modify: `tests/test_deep_crawl_workflow.py`
- Modify: `tests/test_agent.py`

**Interfaces:**
- Main model consumes `context.main_output_tokens`; judge consumes `context.audit_output_tokens`.
- `web_fetch` and `document_read` consume `tool_content_max_bytes()`.

- [ ] Add failing tests for separate main/audit `max_tokens`, optional thinking disablement, bounded fetch preview, bounded document read, and bounded outbound links.
- [ ] Run the focused tests and verify RED.
- [ ] Apply model settings and bound the existing tool return builders.
- [ ] Run the focused tests and verify GREEN.

### Task 4: Search-to-fetch phase gate

**Files:**
- Modify: `src/intel_agent/agent.py`
- Modify: `tests/test_agent.py`

**Interfaces:**
- `AgentDeps.search_calls_with_candidates` tracks only successful candidate-producing searches and resets after successful fetch.

- [ ] Add a failing test showing the fourth candidate-producing search is blocked until a successful fetch.
- [ ] Implement the counter and `FETCH_REQUIRED` response at the existing `web_search` wrapper.
- [ ] Run the focused test and verify GREEN.

### Task 5: Documentation and verification

**Files:**
- Modify: `README.md`
- Modify: `experiments/configs/qwen35-9b-llama-server.yaml`
- Modify: `experiments/CHANGELOG.md`

- [ ] Document the four window choices and local 32K Qwen settings.
- [ ] Run Ruff format/check, Pyright, full pytest, and `uv build`.
- [ ] Run the same real research task against Qwen3.5-9B with 32K context.
- [ ] Record terminal state, elapsed time, search/document/evidence/fact funnel, maximum observed prompt, and report existence.
