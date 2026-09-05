"""HTTP API smoke tests (T19)."""

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


def test_submit_returns_durable_task_without_waiting_for_research(api_client):
    response = api_client.post(
        "/api/tasks", json={"question": "动力电池回收进展"}
    )
    assert response.status_code == 202
    task_id = response.json()["task_id"]
    status = api_client.get(f"/api/tasks/{task_id}")
    assert status.status_code == 200
    assert status.json()["task_id"] == task_id
