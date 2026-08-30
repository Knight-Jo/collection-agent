from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from intel_agent.config import Settings
from intel_agent.conversation import ConversationRuntime
from intel_agent.runner import TaskRunSpec
from intel_agent.state_db import connect_state_db
from intel_agent.state_store import StateStore
from intel_agent.web.app import create_app
from intel_agent.web.runs import LegacyRunAdapter


def _spec() -> TaskRunSpec:
    return TaskRunSpec(topic="兼容主题", questions=["问题一", "问题二"])


@pytest.mark.asyncio
async def test_legacy_adapter_creates_persistent_research_run(cwd):
    store = StateStore(cwd)

    class Initial:
        async def run_initial(
            self,
            run,
            brief,
            cancellation_token,
            *,
            on_event=None,
            recorder=None,
        ):
            store.claim_run(
                run.id,
                phase="planning",
                lease_owner=run.id,
            )
            store.finish_run(
                run.id,
                expected_input_version=run.input_committed_state_version,
                outcome="no_progress",
            )
            return store.get_run(run.id)

    runtime = ConversationRuntime(
        cwd,
        Settings(),
        intake=cast(Any, object()),
        dialogue=cast(Any, object()),
        retriever=cast(Any, object()),
        initial=Initial(),
    )
    adapter = LegacyRunAdapter(cwd, Settings(), runtime=runtime)

    view = await adapter.create(_spec())
    await adapter.wait(view.run_id)

    persisted = store.get_run(view.run_id)
    assert persisted.run_type == "initial"
    assert persisted.status == "succeeded"
    assert adapter.get(view.run_id).status == "completed_with_gaps"


def test_legacy_adapter_maps_durable_events(cwd):
    store = StateStore(cwd)
    task = _make_task(cwd)
    run = store.create_legacy_run(task, input_snapshot={"source": "api"})
    store.claim_run(run.id, phase="planning", lease_owner=run.id)
    store.transition_run(run.id, "failed", error="boom")

    runtime = ConversationRuntime(
        cwd,
        Settings(),
        intake=cast(Any, object()),
        dialogue=cast(Any, object()),
        retriever=cast(Any, object()),
    )
    adapter = LegacyRunAdapter(cwd, Settings(), runtime=runtime)
    events = adapter.events(run.id)

    assert [event.type for event in events] == ["run.started", "run.failed"]
    assert events[-1].data["status"] == "failed"


def test_legacy_adapter_maps_stopping_to_legacy_running(cwd):
    store = StateStore(cwd)
    task = _make_task(cwd)
    run = store.create_legacy_run(task, input_snapshot={"source": "api"})
    store.claim_run(run.id, phase="planning", lease_owner=run.id)
    store.stop_run(run.id)

    runtime = ConversationRuntime(
        cwd,
        Settings(),
        intake=cast(Any, object()),
        dialogue=cast(Any, object()),
        retriever=cast(Any, object()),
    )
    adapter = LegacyRunAdapter(cwd, Settings(), runtime=runtime)

    assert adapter.get(run.id).status == "running"


def test_api_routes_install_legacy_adapter(cwd, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    runtime = ConversationRuntime(
        cwd,
        Settings(),
        intake=cast(Any, object()),
        dialogue=cast(Any, object()),
        retriever=cast(Any, object()),
    )
    app = create_app(
        cwd=cwd, settings=Settings(), conversation_runtime=runtime
    )

    assert isinstance(app.state.registry, LegacyRunAdapter)
    response = TestClient(app).post(
        "/api/runs",
        json={"topic": "兼容主题", "questions": ["问题一", "问题二"]},
    )

    assert response.status_code == 202
    run_id = response.json()["run_id"]
    assert runtime.store.get_run(run_id).run_type == "initial"
    with connect_state_db(cwd) as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM web_run_projections"
            ).fetchone()[0]
            == 0
        )


def _make_task(cwd):
    from intel_agent.task import build_task

    task = build_task(
        "兼容主题",
        ["问题一", "问题二"],
        _spec().criteria,
    )
    return task
