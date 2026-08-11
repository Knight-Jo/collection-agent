"""FastAPI workbench endpoint tests."""

from __future__ import annotations

import sys

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from intel_agent.config import Settings
from intel_agent.web.app import create_app, main
from tests.conftest import new_task


def test_system_and_task_endpoints(cwd, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    task = new_task(cwd)
    client = TestClient(create_app(cwd=cwd, settings=Settings()))

    system = client.get("/api/system")
    tasks = client.get("/api/tasks")
    detail = client.get(f"/api/tasks/{task.id}")

    assert system.status_code == 200
    assert system.json()["model"]["configured"] is True
    assert tasks.json()[0]["id"] == task.id
    assert detail.json()["task"]["topic"] == "测试主题"


def test_create_run_requires_model_key(cwd, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    client = TestClient(create_app(cwd=cwd, settings=Settings()))

    response = client.post(
        "/api/runs",
        json={
            "topic": "测试主题",
            "questions": ["问题甲", "问题乙"],
            "criteria": {
                "min_independent_sources": 2,
                "min_high_quality_sources": 1,
                "recency_days": 90,
                "require_recency": False,
            },
        },
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "MODEL_NOT_CONFIGURED"


def test_missing_task_uses_stable_error_envelope(cwd):
    client = TestClient(create_app(cwd=cwd, settings=Settings()))

    response = client.get("/api/tasks/task-missing")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "NOT_FOUND",
            "message": "记录不存在: tasks/task-missing.json",
        }
    }


def test_missing_run_event_stream_returns_not_found(cwd):
    client = TestClient(create_app(cwd=cwd, settings=Settings()))

    response = client.get("/api/runs/run-missing/events")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_static_frontend_falls_back_to_index(cwd, tmp_path):
    frontend = tmp_path / "dist"
    frontend.mkdir()
    (frontend / "index.html").write_text(
        '<div id="root"></div>', encoding="utf-8"
    )
    client = TestClient(
        create_app(cwd=cwd, settings=Settings(), static_dir=frontend)
    )

    assert client.get("/").status_code == 200
    assert client.get("/tasks/example").text == '<div id="root"></div>'


def test_main_uses_web_binding_from_config(tmp_path, monkeypatch):
    config = tmp_path / "config.yaml"
    config.write_text(
        "web:\n  host: 127.0.0.2\n  port: 9123\n", encoding="utf-8"
    )
    captured = {}
    monkeypatch.setattr(
        sys, "argv", ["intel-agent-web", "--config", str(config)]
    )
    monkeypatch.setattr(
        "intel_agent.web.app.uvicorn.run",
        lambda _app, *, host, port: captured.update(host=host, port=port),
    )

    main()

    assert captured == {"host": "127.0.0.2", "port": 9123}


def test_web_port_must_be_in_tcp_range():
    with pytest.raises(ValidationError):
        Settings.model_validate({"web": {"port": 65_536}})


def test_main_cli_binding_overrides_config(tmp_path, monkeypatch):
    config = tmp_path / "config.yaml"
    config.write_text(
        "web:\n  host: 127.0.0.2\n  port: 9123\n", encoding="utf-8"
    )
    captured = {}
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "intel-agent-web",
            "--config",
            str(config),
            "--host",
            "127.0.0.3",
            "--port",
            "9124",
        ],
    )
    monkeypatch.setattr(
        "intel_agent.web.app.uvicorn.run",
        lambda _app, *, host, port: captured.update(host=host, port=port),
    )

    main()

    assert captured == {"host": "127.0.0.3", "port": 9124}
