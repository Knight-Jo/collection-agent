"""FastAPI routes for persistent task dialogue and report versions."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from ..conversation import ConversationRuntime
from ..models import ActionRequest, Message, ReportVersion, ResearchRun
from .schemas import (
    ActionConfirm,
    ConversationMessageView,
    ConversationView,
    MessageCreate,
    ReportPublishRequest,
)

router = APIRouter(prefix="/api")


def _runtime(request: Request) -> ConversationRuntime:
    return request.app.state.conversation_runtime


@router.get("/tasks/{task_id}/conversation", response_model=ConversationView)
async def conversation_view(request: Request, task_id: str):
    return _runtime(request).conversation_view(task_id)


@router.post(
    "/tasks/{task_id}/conversation/messages",
    response_model=Message,
    status_code=202,
)
async def submit_message(
    request: Request, task_id: str, payload: MessageCreate
) -> Message:
    return _runtime(request).submit_message(
        task_id, payload.content, payload.client_message_id
    )


@router.get("/messages/{message_id}", response_model=ConversationMessageView)
async def message_detail(request: Request, message_id: str):
    runtime = _runtime(request)
    message = runtime.store.reply_for_message(message_id)
    message = message or runtime.store.get_message(message_id)
    value = message.model_dump(mode="json")
    value["citations"] = [
        item.model_dump(mode="json")
        for item in runtime.store.citations_for_message(message.id)
    ]
    return value


@router.post("/messages/{message_id}/cancel", response_model=Message)
async def cancel_message(request: Request, message_id: str) -> Message:
    return await _runtime(request).cancel_message(message_id)


@router.post(
    "/action-requests/{action_id}/confirm", response_model=ActionRequest
)
async def confirm_action(
    request: Request, action_id: str, payload: ActionConfirm
) -> ActionRequest:
    return _runtime(request).confirm_action(
        action_id, payload.client_message_id
    )


@router.post(
    "/action-requests/{action_id}/reject", response_model=ActionRequest
)
async def reject_action(request: Request, action_id: str) -> ActionRequest:
    return _runtime(request).reject_action(action_id)


@router.post(
    "/action-requests/{action_id}/cancel", response_model=ActionRequest
)
async def cancel_action(request: Request, action_id: str) -> ActionRequest:
    return await _runtime(request).cancel_action(action_id)


@router.get("/tasks/{task_id}/research-runs", response_model=list[ResearchRun])
async def research_runs(request: Request, task_id: str) -> list[ResearchRun]:
    return _runtime(request).store.list_runs(task_id)


@router.post("/research-runs/{run_id}/cancel", response_model=ResearchRun)
async def cancel_research_run(request: Request, run_id: str) -> ResearchRun:
    return await _runtime(request).cancel_research_run(run_id)


@router.get(
    "/tasks/{task_id}/report-versions", response_model=list[ReportVersion]
)
async def report_versions(
    request: Request, task_id: str
) -> list[ReportVersion]:
    return _runtime(request).store.list_reports(task_id)


@router.post(
    "/tasks/{task_id}/report-versions",
    response_model=ReportVersion,
    status_code=201,
)
async def create_report_version(
    request: Request, task_id: str
) -> ReportVersion:
    return _runtime(request).publisher.create_draft(task_id)


@router.post(
    "/report-versions/{report_id}/publish", response_model=ReportVersion
)
async def publish_report_version(
    request: Request,
    report_id: str,
    payload: ReportPublishRequest,
) -> ReportVersion:
    return _runtime(request).publisher.publish(
        report_id,
        publish_stale=payload.publish_stale,
        expected_current_state_version=(
            payload.expected_current_state_version
        ),
    )


@router.get("/tasks/{task_id}/conversation/events")
async def conversation_events(
    request: Request, task_id: str
) -> StreamingResponse:
    runtime = _runtime(request)
    runtime.store.get_conversation(task_id)
    try:
        cursor = int(request.headers.get("last-event-id", "0"))
    except ValueError:
        cursor = 0

    async def stream():
        nonlocal cursor
        idle_ticks = 0
        while not await request.is_disconnected():
            events = runtime.store.events_after(task_id, cursor)
            if events:
                idle_ticks = 0
                for event in events:
                    cursor = event.sequence
                    data = json.dumps(event.data, ensure_ascii=False)
                    yield (
                        f"id: {event.sequence}\n"
                        f"event: {event.event_type}\n"
                        f"data: {data}\n\n"
                    )
                continue
            idle_ticks += 1
            if idle_ticks >= 30:
                idle_ticks = 0
                yield ": heartbeat\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
