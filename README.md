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
| `runtime/` | Config, execution pool, and logging |
| `storage/` | SQLite stores: materials/tasks/settings over one connection, content-addressed resources |
| `search/` | Multi-provider search, conservative dedup, RRF fusion |
| `fetch/` | SSRF-safe HTTP transport and streaming acquisition |
| `extraction/` | Backend registry and media routers (HTML/PDF/OCR/Office/audio/video/ASR) |
| `indexing/` | Chunking, lexical tokens, embeddings, vector index, tokenizer |
| `context/` | Scoped retrieval, token budget, citations |
| `agent/`, `orchestration/` | Decision adapter and durable state machine |
| `acquisition.py`, `application.py`, `bootstrap.py` | Pipeline, task lifecycle, assembly |
| `cli.py`, `api/` | CLI and FastAPI entry points |
| `conversation.py`, `monitoring/`, `factcheck/`, `media/`, `library.py` | Conversation research, scheduled monitoring, fact checks, media jobs, library projections |
| `search/settings.py`, `storage/settings.py` | Search configuration and persisted overrides |
| `frontend/` | React workbench using the FastAPI HTTP/SSE surface |

## Quick start

```bash
mamba activate collection-agent-pydantic
export UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX
uv sync --extra dev --extra media

# Select one configuration for both CLI and API.
# Review model, search providers, and storage paths before running.
export INTEL_AGENT_CONFIG="$PWD/configs/default.yaml"

# Run a research task
research-agent run --question "动力电池回收进展"

# Resume / status / import / reindex
research-agent resume --task-id TASK_ID
research-agent status --task-id TASK_ID
research-agent import --task-id TASK_ID --path samples/report.pdf
research-agent reindex --artifact-id ARTIFACT_ID
```

The FastAPI server shares the same engine:

```bash
uv run uvicorn intel_agent.api.app:create_app --factory --host 127.0.0.1 --port 8000 --workers 1
```

The workbench lives in `frontend/` and uses Bun 1.3.14. In another terminal:

```bash
cd frontend
bun install --frozen-lockfile
bun run dev --host 127.0.0.1
```

Vite serves the UI on port 5173 and proxies `/api` to `127.0.0.1:8000`.
The API exposes conversations, research, monitors, fact checks, media,
library, and search settings; inspect `/docs` for the current routes.
Monitor scheduling starts and stops with the shared application lifecycle.
Keep this single-worker service on a trusted local interface; external
access requires separately validated authentication and network controls.

Exit codes: `0` completed, `1` failed/config error, `2` partial, `130`
cancelled. Results are written to `output/<task_id>/result.json` and
`result.md`; SQLite (`data/research.sqlite`) is the authoritative task state.

## Configuration

The typed settings live in `runtime/config.py`; committed examples are in
`configs/default.yaml` (full) and `configs/low-resource.yaml` (text-only).
Settings resolve in this order: explicit CLI `--config`, `INTEL_AGENT_CONFIG`,
then `configs/default.yaml`. A root `config.yaml` is not selected automatically.
Relative paths resolve against the configuration file's directory: moving a
copy requires reviewing its data/output/import paths. Use the same selected
configuration for CLI and API.

Use environment variables for provider credentials and never commit secrets.
The settings UI masks reads, but submitted Key/Cookie overrides currently
persist in SQLite JSON; this is not encrypted credential storage.

Key service endpoints live in the config too:

- `model.*` — the LLM: vLLM/DeepSeek (OpenAI-compatible `api_style: openai`)
  or Ollama; `disable_thinking` turns off the reasoning preamble on vLLM
  reasoning models (e.g. qwen3.8-27b).
- `embedding.*` — the embedding service (e.g. vLLM
  `qwen3-embedding-0.6b`, `dimension: 1024`); set to `null` to fall back to
  lexical-only retrieval.
- `storage.qdrant_url` — the vector database; `null` disables the vector path.
- `extraction.whisper_*` — audio/video transcription via faster-whisper
  (`whisper_model`/`whisper_device`/`whisper_language`); `video_frame_ocr`
  gates on-screen-text OCR of video frames (off by default), `always_asr`
  forces audio transcription even when a subtitle track exists.

## Verification

```bash
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run ruff format --check src tests
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run ruff check src tests
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pyright
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv build
```

From `frontend/`, run `bun run test`, `bun run typecheck`, `bun run check`,
and `bun run build` for workbench verification.

## Documentation and remaining work

- [Domain vocabulary](CONTEXT.md)
- [Documentation index](docs/README.md)
- [Outstanding work](TODO.md)
- [Engine requirements](specs/2026-09-05-search-agent-design.md)
- [Monitoring, fact-checking, and media requirements](specs/002-monitor-factcheck-media/spec.md)

Specifications define targets, not evidence that every requirement has passed.
Historical acceptance records remain under `experiments/`; current status
must be checked against the implementation and a dated verification run.
