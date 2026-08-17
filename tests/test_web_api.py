"""FastAPI workbench endpoint tests."""

from __future__ import annotations

import sys

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from intel_agent.browser import BrowserAvailability
from intel_agent.config import Settings
from intel_agent.models import (
    CrawlEntry,
    CrawlSnapshot,
    ExtractionState,
    utc_now,
)
from intel_agent.storage import save_crawl
from intel_agent.web.app import create_app, main
from intel_agent.web.schemas import RunCreate
from tests.conftest import make_document, new_task


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


def test_system_reports_crawl_default_and_processor_availability(
    cwd, monkeypatch
):
    monkeypatch.setattr(
        "intel_agent.web.app.which",
        lambda command: (
            f"/usr/bin/{command}"
            if command in {"tesseract", "ffmpeg"}
            else None
        ),
    )
    monkeypatch.setattr(
        "intel_agent.web.app.find_spec",
        lambda module: object() if module == "faster_whisper" else None,
    )
    settings = Settings.model_validate(
        {"crawl": {"enabled_by_default": False}}
    )

    response = TestClient(create_app(cwd=cwd, settings=settings)).get(
        "/api/system"
    )

    assert response.status_code == 200
    assert response.json()["crawl"] == {"default_enabled": False}
    assert response.json()["processors"] == {
        "tesseract": True,
        "ffmpeg": True,
        "whisper": True,
        "libreoffice": False,
    }


def test_system_reports_browser_runtime_and_network_mode(cwd, monkeypatch):
    monkeypatch.setattr(
        "intel_agent.web.app.browser_runtime_status",
        lambda: BrowserAvailability(playwright=True, chromium=True),
    )
    settings = Settings.model_validate(
        {
            "fetch": {
                "enable_browser_fallback": True,
                "browser_network_mode": "isolated",
            }
        }
    )

    response = TestClient(create_app(cwd=cwd, settings=settings)).get(
        "/api/system"
    )

    assert response.status_code == 200
    assert response.json()["browser"] == {
        "enabled": True,
        "playwright": True,
        "chromium": True,
        "network_mode": "isolated",
    }


def test_run_create_preserves_deep_crawl_omission():
    payload = {
        "topic": "测试主题",
        "questions": ["问题甲", "问题乙"],
    }

    omitted = RunCreate.model_validate(payload)
    disabled = RunCreate.model_validate({**payload, "deep_crawl": False})

    assert omitted.deep_crawl is None
    assert omitted.to_spec().deep_crawl is None
    assert disabled.to_spec().deep_crawl is False


def test_run_create_accepts_topic_only_research_brief():
    request = RunCreate.model_validate(
        {
            "topic": "测试主题",
            "objective": "了解现状",
            "scope": {"geography": ["中国"]},
            "report_depth": "brief",
        }
    )

    spec = request.to_spec()
    assert spec.questions == []
    assert spec.objective == "了解现状"
    assert spec.scope.geography == ["中国"]
    assert spec.report_depth == "brief"


def test_resource_download_checks_ownership_and_integrity(cwd):
    task = new_task(cwd)
    document = make_document(cwd, "original resource")
    now = utc_now()
    save_crawl(
        cwd,
        CrawlSnapshot(
            task_id=task.id,
            status="complete",
            entries=[
                CrawlEntry(
                    canonical_url=document.canonical_url,
                    depth=0,
                    priority=0,
                    status="complete",
                    downloaded_bytes=len(b"original resource"),
                    document_id=document.id,
                    mime_type=document.content_type,
                    size=len(b"original resource"),
                    extraction=ExtractionState(status="complete"),
                    created_at=now,
                    updated_at=now,
                )
            ],
            created_at=now,
            updated_at=now,
        ),
    )
    client = TestClient(create_app(cwd=cwd, settings=Settings()))

    response = client.get(
        f"/api/tasks/{task.id}/resources/{document.id}/download"
    )

    assert response.status_code == 200
    assert response.content == b"original resource"
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.headers["x-content-type-options"] == "nosniff"

    other_task = new_task(cwd, ["问题丙", "问题丁"])
    unowned = client.get(
        f"/api/tasks/{other_task.id}/resources/{document.id}/download"
    )
    assert unowned.status_code == 404

    (cwd / document.raw_path).write_bytes(b"tampered")
    tampered = client.get(
        f"/api/tasks/{task.id}/resources/{document.id}/download"
    )
    assert tampered.status_code == 409
    assert tampered.json()["error"]["code"] == "DOCUMENT_TAMPERED"


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
