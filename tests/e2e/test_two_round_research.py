"""Real two-round research: LLM + academic search (spec A27)."""

from __future__ import annotations

import os
from pathlib import Path

import httpx2
import pytest

from intel_agent.bootstrap import bootstrap
from intel_agent.runtime.config import load_settings

OLLAMA = "http://127.0.0.1:11434"


def _ollama_ready() -> bool:
    try:
        return httpx2.get(f"{OLLAMA}/api/tags", timeout=2).status_code == 200
    except Exception:  # noqa: BLE001
        return False


def _write_config(tmp_path: Path, proxy: str | None) -> Path:
    fetch_block = (
        "fetch:\n  http_timeout_seconds: 60\n  normal_max_bytes: 31457280\n"
    )
    if proxy:
        fetch_block += f"  proxy_url: {proxy}\n"
    config = tmp_path / "config.yaml"
    config.write_text(
        "model:\n"
        "  model_id: qwen3.5:9b\n"
        "  base_url: http://127.0.0.1:11434\n"
        "  api_key_env: null\n"
        "  api_style: ollama\n"
        "search:\n"
        "  per_provider_limit: 2\n"
        "  total_limit: 4\n"
        "  providers:\n"
        "    searxng:\n"
        "      enabled: false\n"
        "    arxiv:\n"
        "      enabled: true\n"
        "    openalex:\n"
        "      enabled: true\n"
        "    rss:\n"
        "      enabled: false\n"
        "      extra:\n"
        "        feeds: []\n"
        "research:\n"
        "  max_rounds: 2\n"
        "  no_progress_rounds: 2\n" + fetch_block + "storage:\n"
        f"  data_dir: {tmp_path / 'data'}\n"
        f"  output_dir: {tmp_path / 'output'}\n",
        encoding="utf-8",
    )
    return config


def _http_proxy() -> str | None:
    return os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")


@pytest.mark.integration
async def test_two_round_research_produces_cited_answer(tmp_path):
    if not _ollama_ready():
        pytest.skip("ollama not reachable")
    config = _write_config(tmp_path, _http_proxy())
    settings = load_settings(config)
    async with bootstrap(settings) as app:
        result = await app.orchestrator.run(
            "What are the latest advances in transformer attention?"
        )
    assert result.status == "completed"
    assert result.answer
    assert result.citations
    assert result.usage.llm_calls >= 1
    assert result.stop_reason == "evidence_sufficient"
