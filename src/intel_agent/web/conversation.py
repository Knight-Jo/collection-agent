"""FastAPI routes for persistent task dialogue and report versions."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from ..conversation import ConversationRuntime
from ..models import (
    ActionRequest,
    Conversation,
    Message,
    ReportVersion,
    ResearchRun,
    SearchPlanVersion,
    TimelineEntry,
)
from .schemas import (
    ActionConfirm,
    ConversationCreate,
    ConversationListItem,
    ConversationMessageView,
    ConversationView,
    MessageCreate,
    ReportPublishRequest,
    ReportVersionSummary,
    ReportVersionView,
)

router = APIRouter(prefix="/api")


def _runtime(request: Request) -> ConversationRuntime:
    return request.app.state.conversation_runtime


@router.post("/conversations", response_model=Conversation, status_code=201)
async def create_conversation(
    request: Request, payload: ConversationCreate
) -> Conversation:
    return _runtime(request).store.create_conversation(
        payload.client_conversation_id
    )


@router.get("/conversations", response_model=list[ConversationListItem])
async def list_conversations(
    request: Request, archived: bool = False
) -> list[ConversationListItem]:
    store = _runtime(request).store
    items = []
    for conversation in store.list_conversations(archived=archived):
        active_run = None
        if conversation.task_id:
            active_run = next(
                (
                    run
                    for run in reversed(store.list_runs(conversation.task_id))
                    if run.status in {"queued", "running", "stopping"}
                ),
                None,
            )
        items.append(
            ConversationListItem(
                **conversation.model_dump(),
                run_status=active_run.status if active_run else None,
                run_phase=active_run.phase if active_run else None,
            )
        )
    return items


@router.post(
    "/conversations/{conversation_id}/archive", response_model=Conversation
)
async def archive_conversation(
    request: Request, conversation_id: str
) -> Conversation:
    return _runtime(request).store.archive_conversation(conversation_id)


@router.post(
    "/conversations/{conversation_id}/restore", response_model=Conversation
)
async def restore_conversation(
    request: Request, conversation_id: str
) -> Conversation:
    return _runtime(request).store.restore_conversation(conversation_id)


@router.get(
    "/conversations/{conversation_id}", response_model=ConversationView
)
async def conversation_detail(request: Request, conversation_id: str):
    return _runtime(request).conversation_view_by_id(conversation_id)


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=Message,
    status_code=202,
)
async def submit_conversation_message(
    request: Request, conversation_id: str, payload: MessageCreate
) -> Message:
    return _runtime(request).submit_message(
        conversation_id, payload.content, payload.client_message_id
    )


@router.get(
    "/conversations/{conversation_id}/timeline",
    response_model=list[TimelineEntry],
)
async def conversation_timeline(
    request: Request, conversation_id: str, after_sequence: int = 0
) -> list[TimelineEntry]:
    _runtime(request).store.get_conversation_by_id(conversation_id)
    return _runtime(request).store.timeline_after(
        conversation_id, after_sequence
    )


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


@router.post("/messages/{message_id}/retry", response_model=Message)
async def retry_message(request: Request, message_id: str) -> Message:
    return _runtime(request).retry_message(message_id)


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


@router.post("/research-runs/{run_id}/stop", response_model=ResearchRun)
async def stop_research_run(request: Request, run_id: str) -> ResearchRun:
    return _runtime(request).stop_research_run(run_id)


@router.post("/research-runs/{run_id}/retry", response_model=ResearchRun)
async def retry_research_run(request: Request, run_id: str) -> ResearchRun:
    return _runtime(request).retry_research_run(run_id)


@router.get("/research-runs/{run_id}", response_model=ResearchRun)
async def research_run_detail(request: Request, run_id: str) -> ResearchRun:
    return _runtime(request).store.get_run(run_id)


@router.get(
    "/research-runs/{run_id}/search-plan", response_model=SearchPlanVersion
)
async def active_search_plan(
    request: Request, run_id: str
) -> SearchPlanVersion:
    return _runtime(request).store.active_search_plan(run_id)


@router.get(
    "/search-plan-versions/{plan_id}", response_model=SearchPlanVersion
)
async def search_plan_version(
    request: Request, plan_id: str
) -> SearchPlanVersion:
    return _runtime(request).store.get_search_plan_version(plan_id)


@router.get(
    "/tasks/{task_id}/report-versions",
    response_model=list[ReportVersionSummary],
)
async def report_versions(
    request: Request, task_id: str
) -> list[ReportVersionSummary]:
    runtime = _runtime(request)
    return [
        ReportVersionSummary(
            **report.model_dump(), stale=_report_is_stale(runtime, report)
        )
        for report in runtime.store.list_reports(task_id)
    ]


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


@router.get("/report-versions/{report_id}", response_model=ReportVersionView)
async def report_version_detail(
    request: Request, report_id: str
) -> ReportVersionView:
    report, content = _runtime(request).publisher.read(report_id)
    runtime = _runtime(request)
    return ReportVersionView(
        **report.model_dump(),
        content=content,
        stale=_report_is_stale(runtime, report),
    )


def _report_is_stale(
    runtime: ConversationRuntime, report: ReportVersion
) -> bool:
    snapshot = runtime.store.committed_snapshot(report.task_id)
    return report.based_on_committed_state_version != snapshot.version or (
        report.snapshot_fingerprint is not None
        and report.snapshot_fingerprint != snapshot.fingerprint
    )


@router.get("/tasks/{task_id}/conversation/events")
async def conversation_events(
    request: Request, task_id: str
) -> StreamingResponse:
    runtime = _runtime(request)
    runtime.conversation_view(task_id)
    conversation = runtime.store.get_conversation(task_id)
    return _conversation_event_stream(request, conversation.id)


@router.get("/conversations/{conversation_id}/events")
async def conversation_event_stream(
    request: Request, conversation_id: str
) -> StreamingResponse:
    _runtime(request).store.get_conversation_by_id(conversation_id)
    return _conversation_event_stream(request, conversation_id)


def _conversation_event_stream(
    request: Request, conversation_id: str
) -> StreamingResponse:
    runtime = _runtime(request)
    try:
        cursor = int(request.headers.get("last-event-id", "0"))
    except ValueError:
        cursor = 0

    async def stream():
        nonlocal cursor
        idle_ticks = 0
        async with runtime.transient_events(conversation_id) as transient:
            while not await request.is_disconnected():
                events = runtime.store.events_after_conversation(
                    conversation_id, cursor
                )
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
                try:
                    event_type, payload = await asyncio.wait_for(
                        transient.get(), timeout=0.5
                    )
                except TimeoutError:
                    idle_ticks += 1
                    if idle_ticks >= 30:
                        idle_ticks = 0
                        yield ": heartbeat\n\n"
                else:
                    idle_ticks = 0
                    data = json.dumps(payload, ensure_ascii=False)
                    yield f"event: {event_type}\ndata: {data}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
