from __future__ import annotations

import time

from fastapi.testclient import TestClient

from intel_agent.config import Settings
from intel_agent.conversation import ConversationRuntime
from intel_agent.dialogue import DialogueAction, DialogueDecision
from intel_agent.web.app import create_app
from tests.conftest import new_task


class _Retriever:
    def seed_completed_task(self, _task_id):
        return None

    def retrieve(self, _task_id, _query, *, limit=8):
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

    async def summarize(self, _messages):
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

    with TestClient(app).stream(
        "GET",
        f"/api/tasks/{task.id}/conversation/events",
        headers={"Last-Event-ID": str(first.sequence)},
    ) as response:
        lines = response.iter_lines()
        payload = [next(lines) for _ in range(3)]

    assert response.status_code == 200
    assert payload[0].endswith("2")
    assert payload[1] == "event: test.second"


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
