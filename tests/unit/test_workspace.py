"""Workspace storage + search-settings tests (spec 002 §2, §6)."""

from __future__ import annotations

from datetime import UTC, datetime

from intel_agent.monitoring.models import Monitor, MonitorSchedule
from intel_agent.runtime.config import (
    AI_SEARCH_TOOL_NAMES,
    ProviderConfig,
    ResearchSettings,
    SearchConfig,
)
from intel_agent.search.settings import SearchSettings
from intel_agent.storage.monitoring import MonitoringStore
from intel_agent.storage.settings import SettingsStore
from intel_agent.storage.sqlite import SqliteStore
from intel_agent.storage.tasks import TaskStore


def test_task_store_kind_round_trip(tmp_path):
    task_store = TaskStore(SqliteStore(tmp_path / "t.sqlite"))
    task = task_store.create_task("q", kind="monitor")
    assert task.kind == "monitor"
    loaded = task_store.get_task(task.task_id)
    assert loaded.kind == "monitor"
    assert loaded.status == "queued"

    attempt = task_store.claim_queued(task.task_id)
    assert attempt == 1
    assert task_store.get_task(task.task_id).status == "running"

    task_store.update_task_status(task.task_id, "completed", phase="done")
    assert task_store.get_task(task.task_id).status == "completed"


def test_settings_state_round_trip(material_store):
    store = SettingsStore(material_store.db)
    assert store.get("search") is None
    store.set("search", {"enabled": True})
    assert store.get("search") == {"enabled": True}
    store.set("search", ["arxiv"])
    assert store.get("search") == ["arxiv"]


def test_monitoring_store_round_trip(tmp_path):
    store = MonitoringStore(SqliteStore(tmp_path / "m.sqlite"))
    now = datetime.now(UTC)
    monitor = Monitor(
        monitor_id="mon1",
        name="n",
        subject="s",
        strategy="g",
        schedule=MonitorSchedule(
            cadence="daily", local_time="09:00", timezone="UTC"
        ),
        created_at=now,
        updated_at=now,
    )
    store.save_monitor(monitor)
    loaded = store.get_monitor("mon1")
    assert loaded.name == "n"
    assert loaded.schedule.cadence == "daily"


def test_search_settings_split_and_secret_masking(tmp_path):
    settings = ResearchSettings(
        search=SearchConfig(
            providers={
                "searxng": ProviderConfig(enabled=True, base_url="http://x"),
                "exa": ProviderConfig(enabled=True, api_key_env="EXA_API_KEY"),
                "arxiv": ProviderConfig(enabled=True),
            }
        )
    )
    store = SettingsStore(SqliteStore(tmp_path / "s.sqlite"))
    svc = SearchSettings(settings, store)

    sources = svc.search_sources()
    source_ids = {s["id"] for s in sources}
    assert "searxng" in source_ids
    assert "arxiv" in source_ids
    assert not (source_ids & AI_SEARCH_TOOL_NAMES)

    tools = svc.ai_search_tools()
    tool_ids = {t["id"] for t in tools}
    assert tool_ids == {"brave", "exa", "tavily"}
    for tool in tools:
        assert "api_key_configured" in tool
        assert "api_key" not in tool

    # toggle persists and is secret-free on read
    svc.toggle_ai_tool("exa")
    assert any(
        t["id"] == "exa" and t["enabled"] is False
        for t in svc.ai_search_tools()
    )
