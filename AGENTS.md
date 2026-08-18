# Repository Guidelines

## Project Structure & Module Organization

Production code lives in `src/intel_agent/`; modules are split by responsibility, such as `agent.py`, `models.py`, `storage.py`, and `main.py`. Tests live in `tests/` and generally mirror module names (`test_task.py`, `test_security.py`). Use `scripts/` for experiment utilities and `experiments/` for run manifests and reports. `experiments/` holds iterative agent runs (`runs/NNN-name/` with manifest, trace, state snapshot, and report) plus a cross-run `ROADMAP.md`; the operating spec for running and observing experiments lives in `experiments/AGENTS.md`. Runtime `data/`, `output/`, and local `config.yaml` are generated or ignored; do not commit them.

## Build, Test, and Development Commands

Use Python 3.12 through the `collection-agent-pydantic` conda environment and manage dependencies only with `uv`:

```bash
mamba activate collection-agent-pydantic
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv sync --extra dev
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run ruff format .
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run ruff check .
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pyright
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv build
```

The local workbench lives in `web/` and uses Bun 1.3.14. Run `bun install --frozen-lockfile`, `bun run test`, `bun run typecheck`, and `bun run build` from that directory. Commit `bun.lock`, but never `node_modules/` or `dist/`.

Copy `config.example.yaml` to `config.yaml` before running `python -m intel_agent`. Use `uv add` or `uv remove` instead of installing project dependencies directly with `pip`.

## Coding Style & Static Checks

Follow PEP 8 with four-space indentation, `snake_case` functions and modules, `PascalCase` classes, and `UPPER_SNAKE_CASE` constants. Prefer type annotations, small single-purpose functions, `pathlib.Path`, and descriptive names. Group imports as standard library, third-party, then local.

Ruff is the required formatter and linter. Configuration in `pyproject.toml` targets Python 3.12, uses a 79-character line length, and enables `E`, `W`, `F`, `I`, `UP`, `B`, and `SIM`. Run `ruff format --check .` and `ruff check .` before committing. Do not bypass rules with `noqa` unless the exception is narrow and documented.

Pyright runs in `basic` mode across `src/`, `scripts/`, and `tests/`. Run `pyright` before committing; fix errors instead of weakening project-wide checks.

## Comments and documentation:

- use english to write comments
- Prefer self-explanatory code over comments.
- Comments should explain why, constraints, assumptions, or non-obvious behavior.
- Do not write comments that merely restate the code.
- Public APIs should have concise docstrings.
- Complex algorithms and workarounds should document their rationale.
- If a change affects public behavior, configuration, APIs, deployment,
  data formats, or architecture, update the relevant documentation.
- Do not modify documentation for purely internal changes unless necessary.
- Keep documentation consistent with the implementation.

## Comments & Documentation

Prefer self-explanatory code. Comments should explain intent, constraints, assumptions, or non-obvious behavior rather than restating code. Public APIs should have concise docstrings. Update relevant documentation when behavior, configuration, APIs, data formats, or architecture change.

## Testing Guidelines

Tests use `pytest`; async tests use `pytest-asyncio` auto mode. Name files `test_<module>.py` and tests `test_<behavior>`. Reuse fixtures from `tests/conftest.py`, isolate filesystem work with temporary paths, and add a focused regression test for every behavior change. No numeric coverage gate is configured.

## Commit & Pull Request Guidelines

Follow the repository’s concise Conventional Commit pattern: `feat(run5): ...`, `fix(run2): ...`, `docs: ...`, or `chore: ...`. Keep commits scoped and imperative. Pull requests should explain the problem and solution, link relevant issues, list verification commands, and call out configuration, security, or generated-output changes. Never commit API keys or populated local configuration.
