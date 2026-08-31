from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence

from fastapi import Request
from fastapi.testclient import TestClient

import intel_agent.continuation as continuation_module
from intel_agent.config import Settings
from intel_agent.continuation import ContinuationRunner
from intel_agent.conversation import ConversationRuntime
from intel_agent.dialogue import DialogueAction, DialogueDecision
from intel_agent.intake import IntakeDecision
from intel_agent.materials import register_material
from intel_agent.models import Message, ResearchBrief
from intel_agent.report import generate_research_report
from intel_agent.retrieval import RetrievedPassage
from intel_agent.storage import sha256, workspace_path
from intel_agent.task import load_task, save_task
from intel_agent.web.app import create_app
from intel_agent.web.conversation import conversation_events
from tests.conftest import make_document, new_task
from tests.test_report import report_draft, seed_reportable_task


class _Retriever:
    def seed_completed_task(self, task_id: str) -> None:
        del task_id
        return None

    def retrieve(
        self, task_id: str, query: str, *, limit: int = 8
    ) -> list[RetrievedPassage]:
        del task_id, query, limit
        return []


class _Dialogue:
    def __init__(self, *, proposed=False):
        self.proposed = proposed

    async def answer(self, **_kwargs):
        action = (
            DialogueAction(
                type="continue_research",
                request_mode="proposed",
                scope={"topic": "供应商"},
            )
            if self.proposed
            else None
        )
        return DialogueDecision(
            intent="continue_research" if action else "ask_evidence",
            answer="当前材料回答",
            answerability="answered",
            cited_passage_ids=[],
            gaps=[],
            action=action,
        )

    async def summarize(
        self,
        messages: Sequence[Message],
        *,
        previous_summary: str = "",
    ) -> str:
        del previous_summary
        del messages
        return "摘要"


class _Intake:
    async def decide(self, query: str, messages: Sequence[Message]):
        del messages
        return IntakeDecision(
            intent="capability_query",
            reply=f"可开展公开信息调研：{query}",
        )


def _wait_completed(client: TestClient, message_id: str):
    for _ in range(50):
        response = client.get(f"/api/messages/{message_id}")
        if response.json()["status"] in {"completed", "failed"}:
            return response
        time.sleep(0.01)
    raise AssertionError("message did not complete")


def test_conversation_message_round_trip(cwd):
    task = new_task(cwd)
    runtime = ConversationRuntime(
        cwd, dialogue=_Dialogue(), retriever=_Retriever()
    )
    client = TestClient(
        create_app(
            cwd=cwd,
            settings=Settings(),
            conversation_runtime=runtime,
        )
    )

    accepted = client.post(
        f"/api/tasks/{task.id}/conversation/messages",
        json={"content": "当前结论？", "client_message_id": "browser-1"},
    )
    completed = _wait_completed(client, accepted.json()["id"])
    projection = client.get(f"/api/tasks/{task.id}/conversation")

    assert accepted.status_code == 202
    assert completed.status_code == 200
    assert completed.json()["content"] == "当前材料回答"
    assert len(projection.json()["messages"]) == 2


def test_conversation_projection_blocks_report_until_verified_report_exists(
    cwd,
):
    task = new_task(cwd)
    runtime = ConversationRuntime(
        cwd, dialogue=_Dialogue(), retriever=_Retriever()
    )
    client = TestClient(
        create_app(
            cwd=cwd,
            settings=Settings(),
            conversation_runtime=runtime,
        )
    )

    projection = client.get(f"/api/tasks/{task.id}/conversation").json()

    assert projection["report_ready"] is False


def test_conversation_projection_allows_report_after_verified_report_exists(
    cwd,
):
    task, facts, _documents = seed_reportable_task(cwd)
    generate_research_report(cwd, task.id, report_draft(task, facts))
    runtime = ConversationRuntime(
        cwd, dialogue=_Dialogue(), retriever=_Retriever()
    )
    client = TestClient(
        create_app(
            cwd=cwd,
            settings=Settings(),
            conversation_runtime=runtime,
        )
    )

    projection = client.get(f"/api/tasks/{task.id}/conversation").json()

    assert projection["report_ready"] is True


def test_task_view_hides_assets_staged_after_committed_baseline(cwd):
    task = new_task(cwd)
    runtime = ConversationRuntime(
        cwd, dialogue=_Dialogue(), retriever=_Retriever()
    )
    runtime.conversation_view(task.id)
    document = make_document(cwd, "uncommitted material")
    register_material(
        cwd, task.id, document.canonical_url, document_id=document.id
    )
    client = TestClient(
        create_app(
            cwd=cwd,
            settings=Settings(),
            conversation_runtime=runtime,
        )
    )

    response = client.get(f"/api/tasks/{task.id}")

    assert response.status_code == 200
    assert response.json()["resources"] == []


def test_conversation_first_intake_round_trip(cwd):
    runtime = ConversationRuntime(
        cwd,
        intake=_Intake(),
        dialogue=_Dialogue(),
        retriever=_Retriever(),
    )
    client = TestClient(
        create_app(
            cwd=cwd,
            settings=Settings(),
            conversation_runtime=runtime,
        )
    )

    created = client.post("/api/conversations", json={})
    conversation_id = created.json()["id"]
    accepted = client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"content": "你能做什么？", "client_message_id": "browser-1"},
    )
    completed = _wait_completed(client, accepted.json()["id"])
    projection = client.get(f"/api/conversations/{conversation_id}")

    assert created.status_code == 201
    assert created.json()["task_id"] is None
    assert completed.json()["content"].startswith("可开展公开信息调研")
    assert projection.json()["conversation"]["status"] == "intake"
    assert client.get("/api/conversations").json()[0]["id"] == conversation_id


def test_conversation_list_includes_current_research_progress(cwd):
    task = new_task(cwd)
    runtime = ConversationRuntime(
        cwd, dialogue=_Dialogue(), retriever=_Retriever()
    )
    runtime.conversation_view(task.id)
    run = runtime.store.create_run(task.id, "initial", 0, {})
    runtime.store.claim_run(run.id, phase="collecting", lease_owner="worker")
    client = TestClient(
        create_app(
            cwd=cwd,
            settings=Settings(),
            conversation_runtime=runtime,
        )
    )

    conversation = client.get("/api/conversations").json()[0]

    assert conversation["run_status"] == "running"
    assert conversation["run_phase"] == "collecting"


def test_conversation_can_be_archived_and_restored(cwd):
    runtime = ConversationRuntime(
        cwd,
        intake=_Intake(),
        dialogue=_Dialogue(),
        retriever=_Retriever(),
    )
    client = TestClient(
        create_app(
            cwd=cwd,
            settings=Settings(),
            conversation_runtime=runtime,
        )
    )
    created = client.post("/api/conversations", json={}).json()

    archived = client.post(f"/api/conversations/{created['id']}/archive")

    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"
    assert client.get("/api/conversations").json() == []
    assert (
        client.get("/api/conversations?archived=true").json()[0]["id"]
        == (created["id"])
    )

    restored = client.post(f"/api/conversations/{created['id']}/restore")

    assert restored.status_code == 200
    assert restored.json()["status"] == "intake"
    assert client.get("/api/conversations").json()[0]["id"] == created["id"]


def test_archived_conversation_rejects_new_messages(cwd):
    runtime = ConversationRuntime(cwd, intake=_Intake())
    client = TestClient(
        create_app(
            cwd=cwd,
            settings=Settings(),
            conversation_runtime=runtime,
        )
    )
    created = client.post("/api/conversations", json={}).json()
    client.post(f"/api/conversations/{created['id']}/archive")

    response = client.post(
        f"/api/conversations/{created['id']}/messages",
        json={"content": "继续", "client_message_id": "browser-1"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONVERSATION_ARCHIVED"


def test_conversation_timeline_uses_own_cursor(cwd):
    runtime = ConversationRuntime(
        cwd,
        intake=_Intake(),
        dialogue=_Dialogue(),
        retriever=_Retriever(),
    )
    conversation = runtime.create_conversation()
    runtime.store.add_user_message(conversation.id, "问题一", "client-1")
    runtime.store.add_user_message(conversation.id, "问题二", "client-2")
    client = TestClient(
        create_app(
            cwd=cwd,
            settings=Settings(),
            conversation_runtime=runtime,
        )
    )

    response = client.get(
        f"/api/conversations/{conversation.id}/timeline?after_sequence=1"
    )

    assert response.status_code == 200
    assert [item["timeline_sequence"] for item in response.json()] == [2]


def test_run_cancel_and_stop_endpoints_are_state_specific(cwd):
    task = new_task(cwd)
    runtime = ConversationRuntime(
        cwd, dialogue=_Dialogue(), retriever=_Retriever()
    )
    runtime.store.register_task(task.id)
    queued = runtime.store.create_run(task.id, "initial", 0, {})
    running = runtime.store.create_run(task.id, "initial", 0, {})
    runtime.store.transition_run(running.id, "running")
    client = TestClient(
        create_app(
            cwd=cwd,
            settings=Settings(),
            conversation_runtime=runtime,
        )
    )

    cancelled = client.post(f"/api/research-runs/{queued.id}/cancel")
    stopping = client.post(f"/api/research-runs/{running.id}/stop")

    assert cancelled.json()["status"] == "cancelled"
    assert stopping.json()["status"] == "stopping"


def test_search_plan_history_opens_by_stable_version_id(cwd):
    task = new_task(cwd)
    runtime = ConversationRuntime(
        cwd, dialogue=_Dialogue(), retriever=_Retriever()
    )
    runtime.store.register_task(task.id)
    run = runtime.store.create_run(task.id, "initial", 0, {})
    first = runtime.store.create_search_plan_version(
        run.id, {"queries": ["先进封装"]}
    )
    runtime.store.create_search_plan_version(
        run.id, {"queries": ["先进封装 竞争格局"]}
    )
    client = TestClient(
        create_app(
            cwd=cwd,
            settings=Settings(),
            conversation_runtime=runtime,
        )
    )

    historical = client.get(f"/api/search-plan-versions/{first.id}")
    active = client.get(f"/api/research-runs/{run.id}/search-plan")

    assert historical.json()["plan"]["queries"] == ["先进封装"]
    assert active.json()["sequence"] == 2


def test_proposal_can_be_rejected(cwd):
    task = new_task(cwd)
    runtime = ConversationRuntime(
        cwd, dialogue=_Dialogue(proposed=True), retriever=_Retriever()
    )
    client = TestClient(
        create_app(
            cwd=cwd,
            settings=Settings(),
            conversation_runtime=runtime,
        )
    )
    accepted = client.post(
        f"/api/tasks/{task.id}/conversation/messages",
        json={"content": "材料够吗？", "client_message_id": "browser-1"},
    )
    _wait_completed(client, accepted.json()["id"])
    action_id = client.get(f"/api/tasks/{task.id}/conversation").json()[
        "actions"
    ][0]["id"]

    rejected = client.post(f"/api/action-requests/{action_id}/reject")

    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"


def test_conversation_rejects_unknown_task(cwd):
    runtime = ConversationRuntime(
        cwd, dialogue=_Dialogue(), retriever=_Retriever()
    )
    client = TestClient(
        create_app(
            cwd=cwd,
            settings=Settings(),
            conversation_runtime=runtime,
        )
    )

    response = client.get("/api/tasks/missing/conversation")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_conversation_events_replay_last_event_id(cwd):
    task = new_task(cwd)
    runtime = ConversationRuntime(
        cwd, dialogue=_Dialogue(), retriever=_Retriever()
    )
    runtime.store.register_task(task.id)
    first = runtime.store.append_event(task.id, "test.first", {})
    runtime.store.append_event(task.id, "test.second", {"value": 2})
    app = create_app(
        cwd=cwd,
        settings=Settings(),
        conversation_runtime=runtime,
    )

    async def first_chunk():
        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": f"/api/tasks/{task.id}/conversation/events",
                "headers": [(b"last-event-id", str(first.sequence).encode())],
                "app": app,
            },
            receive,
        )
        response = await conversation_events(request, task.id)
        async for chunk in response.body_iterator:
            return chunk
        raise AssertionError("event stream returned no events")

    payload = asyncio.run(first_chunk())

    assert str(payload).startswith("id: 2")
    assert "event: test.second" in str(payload)


def test_conversation_event_stream_redacts_credentials(cwd):
    task = new_task(cwd)
    runtime = ConversationRuntime(
        cwd, dialogue=_Dialogue(), retriever=_Retriever()
    )
    runtime.store.register_task(task.id)
    runtime.store.append_event(
        task.id,
        "test.secret",
        {"url": "https://example.com/?token=secret"},
    )
    app = create_app(
        cwd=cwd, settings=Settings(), conversation_runtime=runtime
    )

    async def read_chunk():
        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        response = await conversation_events(
            Request(
                {
                    "type": "http",
                    "method": "GET",
                    "path": f"/api/tasks/{task.id}/conversation/events",
                    "headers": [],
                    "app": app,
                },
                receive,
            ),
            task.id,
        )
        async for chunk in response.body_iterator:
            return str(chunk)
        raise AssertionError("event stream returned no events")

    payload = asyncio.run(read_chunk())
    assert "token=secret" not in payload
    assert "token=%2A%2A%2A" in payload


def test_conversation_events_forward_transient_answer_delta(cwd):
    task = new_task(cwd)
    runtime = ConversationRuntime(
        cwd, dialogue=_Dialogue(), retriever=_Retriever()
    )
    runtime.conversation_view(task.id)
    conversation = runtime.store.get_conversation(task.id)
    app = create_app(
        cwd=cwd,
        settings=Settings(),
        conversation_runtime=runtime,
    )

    async def first_chunk():
        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": f"/api/conversations/{conversation.id}/events",
                "headers": [(b"last-event-id", b"1")],
                "app": app,
            },
            receive,
        )
        response = await conversation_events(request, task.id)

        async def next_chunk():
            async for chunk in response.body_iterator:
                return chunk
            raise AssertionError("event stream returned no events")

        pending = asyncio.create_task(next_chunk())
        await asyncio.sleep(0)
        runtime.publish_transient(
            conversation.id,
            "answer.delta",
            {"reply_to_id": "message-user", "delta": "部分回答"},
        )
        return await asyncio.wait_for(pending, timeout=1)

    payload = str(asyncio.run(first_chunk()))

    assert "event: answer.delta" in payload
    assert '"delta": "部分回答"' in payload
    assert not payload.startswith("id:")


async def test_initial_research_publishes_stage_progress(monkeypatch, cwd):
    task = new_task(cwd)
    runner = ContinuationRunner(cwd)
    runtime = ConversationRuntime(
        cwd,
        dialogue=_Dialogue(),
        retriever=_Retriever(),
        initial=runner,
    )
    runtime.conversation_view(task.id)
    run = runtime.store.create_run(task.id, "initial", 0, {})
    conversation = runtime.store.get_conversation(task.id)

    async def fake_agent_task(_cwd, _settings, _spec, **kwargs):
        current = load_task(cwd, task.id)
        save_task(cwd, current.model_copy(update={"stage": "assess"}))
        await kwargs["on_event"](object())

    monkeypatch.setattr(continuation_module, "run_agent_task", fake_agent_task)

    async with runtime.transient_events(conversation.id) as events:
        runtime._schedule_initial(
            run,
            ResearchBrief(topic=task.topic, key_questions=["问题"]),
        )
        event_type, payload = await asyncio.wait_for(events.get(), timeout=1)
        await runtime.wait_research_run(run.id)

    assert event_type == "run.progress"
    assert payload == {"run_id": run.id, "phase": "assessing"}
    assert runtime.store.get_run(run.id).phase == "checkpointing"


def test_report_publish_errors_remain_structured(cwd):
    new_task(cwd)
    runtime = ConversationRuntime(
        cwd, dialogue=_Dialogue(), retriever=_Retriever()
    )
    client = TestClient(
        create_app(
            cwd=cwd,
            settings=Settings(),
            conversation_runtime=runtime,
        )
    )

    response = client.post("/api/report-versions/missing/publish", json={})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_report_version_detail_returns_verified_markdown(cwd):
    task = new_task(cwd)
    runtime = ConversationRuntime(
        cwd, dialogue=_Dialogue(), retriever=_Retriever()
    )
    runtime.store.register_task(task.id)
    relative_path = "output/report-versions/report-1.md"
    path = workspace_path(cwd, relative_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# 调研报告\n\n核心结论。", encoding="utf-8")
    report = runtime.store.create_report_draft(
        task.id, relative_path, sha256(path.read_bytes())
    )
    client = TestClient(
        create_app(
            cwd=cwd,
            settings=Settings(),
            conversation_runtime=runtime,
        )
    )

    response = client.get(f"/api/report-versions/{report.id}")

    assert response.status_code == 200
    assert response.json()["content"] == "# 调研报告\n\n核心结论。"
    assert response.json()["stale"] is False
