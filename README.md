# collection-agent-pydantic

A modular, loopable research agent (v0.1). Given a question, it searches for
material, fetches and extracts raw sources, stores traceable materials, and
lets a research agent decide whether the evidence is sufficient or another
round of research is needed.

The system is a Python modular monolith with a Search → Fetch → Extract →
Normalize → Store → Index → Context pipeline, wrapped by a deterministic
orchestrator. SQLite is the authority for business records, files hold
immutable resources, Qdrant is the rebuildable vector index, and the agent
only produces research decisions.

## Architecture

```
ResearchAgent ──▶ ResearchOrchestrator ──▶ SearchService ──▶ AcquisitionPipeline
                        │                        │                  │
                        ▼                        ▼                  ▼
                 ContextManager ──▶ IndexingService ◀── Fetch/Extract/Normalize
                        │
                        ▼
                 MaterialStore (SQLite) + ResourceStore (files)
```

| Module | Responsibility |
| --- | --- |
| `contracts/` | Cross-module models, errors, and ports |
| `runtime/` | Config, limits, budget/attempt ledgers, executor |
| `storage/` | SQLite material store, content-addressed resources |
| `search/` | Multi-provider search, conservative dedup, RRF fusion |
| `fetch/` | SSRF-safe HTTP transport and streaming acquisition |
| `extraction/` | Backend registry and media routers (HTML/PDF/OCR/Office/audio/video) |
| `indexing/` | Chunking, lexical tokens, vector index, tokenizer |
| `context/` | Scoped retrieval, token budget, citations |
| `agent/`, `orchestration/` | Decision adapter and durable state machine |
| `acquisition.py`, `application.py`, `bootstrap.py` | Pipeline, task lifecycle, assembly |
| `cli.py`, `api/` | CLI and FastAPI entry points |

## Quick start

```bash
mamba activate collection-agent-pydantic
export UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX
uv sync --extra dev --extra media

# Configure a config file (see configs/default.yaml)
cp configs/default.yaml config.yaml
# edit model.base_url, model.api_key_env, search.providers, storage paths

# Check configured capabilities (offline-safe)
research-agent --config config.yaml preflight

# Run a research task
research-agent --config config.yaml run --question "动力电池回收进展"

# Resume / status / import / reindex
research-agent --config config.yaml resume --task-id TASK_ID
research-agent --config config.yaml status --task-id TASK_ID
research-agent --config config.yaml import --task-id TASK_ID --path samples/report.pdf
research-agent --config config.yaml reindex --artifact-id ARTIFACT_ID
```

The FastAPI server shares the same engine:

```bash
uv run uvicorn intel_agent.api.app:create_app --factory --host 127.0.0.1 --port 8000 --workers 1
```

Exit codes: `0` completed, `1` failed/config error, `2` partial, `130`
cancelled. Results are written to `output/<task_id>/result.json` and
`result.md`; SQLite (`data/research.sqlite`) is the authoritative task state.

## Configuration

The typed settings live in `runtime/config.py`; committed examples are in
`configs/default.yaml` (full) and `configs/low-resource.yaml` (text-only).
All §14 resource limits live in one place. Secrets are injected via
environment variables, never committed. Relative paths resolve against the
config file directory so the CLI and API never produce two data sets.

## Verification

```bash
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run ruff format --check src tests
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run ruff check src tests
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pyright
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv build
```

The refactor spec and implementation plan are `specs/2026-09-05-search-agent-design.md`
and `docs/development/search-agent-refactor-plan.md`.
