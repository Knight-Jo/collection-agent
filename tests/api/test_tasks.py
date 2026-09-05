"""HTTP API smoke tests for the conversation surface."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    from intel_agent.api.app import create_app

    config = tmp_path / "config.yaml"
    config.write_text(
        f"storage:\n  data_dir: {tmp_path / 'data'}\n"
        f"  output_dir: {tmp_path / 'output'}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("INTEL_AGENT_CONFIG", str(config))
    app = create_app()
    with TestClient(app) as client:
        yield client


def test_health(api_client):
    response = api_client.get("/api/health")
    assert response.status_code == 200


def test_create_and_get_conversation(api_client):
    response = api_client.post("/api/conversations")
    assert response.status_code == 200
    conversation_id = response.json()["id"]
    assert conversation_id

    detail = api_client.get(f"/api/conversations/{conversation_id}")
    assert detail.status_code == 200
    projection = detail.json()
    assert projection["conversation"]["id"] == conversation_id
    assert projection["messages"] == []
    assert projection["timeline"] == []
    assert projection["materials"] == []


def test_system_status(api_client):
    response = api_client.get("/api/system")
    assert response.status_code == 200
    body = response.json()
    assert "model" in body
    assert "search" in body
    assert "processors" in body


def test_search_sources(api_client):
    response = api_client.get("/api/search-sources")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
