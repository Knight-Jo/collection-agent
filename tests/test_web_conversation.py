from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence

from fastapi import Request
from fastapi.testclient import TestClient

from intel_agent.config import Settings
from intel_agent.conversation import ConversationRuntime
from intel_agent.dialogue import DialogueAction, DialogueDecision
from intel_agent.models import Message
from intel_agent.retrieval import RetrievedPassage
from intel_agent.web.app import create_app
from intel_agent.web.conversation import conversation_events
from tests.conftest import new_task


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

    async def summarize(self, messages: Sequence[Message]) -> str:
        del messages
        return "摘要"


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
