"""Workspace API routes: monitors, fact checks, media, tasks (spec 002 §6)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ...contracts.errors import DomainError

router = APIRouter()


def _app(request: Request):
    return request.app.state.application


def _map(error: DomainError) -> HTTPException:
    mapping = {
        "NOT_FOUND": 404,
        "INVALID_REQUEST": 422,
        "CONFLICT": 409,
        "TOO_LARGE": 413,
        "UNSUPPORTED_MEDIA": 415,
    }
    return HTTPException(mapping.get(error.code, 500), error.message)


# --- monitors ---------------------------------------------------------------


@router.post("/monitors")
async def create_monitor(request: Request, body: dict):
    app = _app(request)
    try:
        return app.monitoring.create_monitor(
            name=(body or {}).get("name", "").strip(),
            subject=(body or {}).get("subject", "").strip(),
            strategy=(body or {}).get("strategy", "").strip(),
            schedule=(body or {}).get("schedule") or {},
            questions=(body or {}).get("questions") or [],
            websites=(body or {}).get("websites") or [],
        ).model_dump(mode="json")
    except DomainError as error:
        raise _map(error) from error


@router.get("/monitors")
async def list_monitors(request: Request):
    return [m.model_dump(mode="json") for m in _app(request).monitoring.list()]


@router.get("/monitors/{monitor_id}")
async def get_monitor(request: Request, monitor_id: str):
    try:
        return _app(request).monitoring.get(monitor_id).model_dump(mode="json")
    except DomainError as error:
        raise _map(error) from error


@router.patch("/monitors/{monitor_id}")
async def update_monitor(request: Request, monitor_id: str, body: dict):
    try:
        return (
            _app(request)
            .monitoring.update_monitor(monitor_id, body or {})
            .model_dump(mode="json")
        )
    except DomainError as error:
        raise _map(error) from error


@router.post("/monitors/{monitor_id}/runs")
async def run_monitor(request: Request, monitor_id: str, body: dict):
    try:
        trigger = (body or {}).get("trigger", "manual")
        run = await _app(request).monitoring.submit_run(monitor_id, trigger)
        return run.model_dump(mode="json")
    except DomainError as error:
        raise _map(error) from error


# --- fact checks ------------------------------------------------------------


@router.post("/fact-checks")
async def create_fact_check(request: Request, body: dict):
    try:
        claim = (body or {}).get("claim", "")
        return _app(request).factcheck.submit(claim).model_dump(mode="json")
    except DomainError as error:
        raise _map(error) from error


@router.get("/fact-checks")
async def list_fact_checks(request: Request):
    return [
        _app(request).factcheck.get(fc.fact_check_id).model_dump(mode="json")
        for fc in _app(request).factcheck.list()
    ]


@router.get("/fact-checks/{fact_check_id}")
async def get_fact_check(request: Request, fact_check_id: str):
    try:
        return (
            _app(request).factcheck.get(fact_check_id).model_dump(mode="json")
        )
    except DomainError as error:
        raise _map(error) from error


# --- media ------------------------------------------------------------------


@router.post("/media")
async def create_media(request: Request, body: dict):
    app = _app(request)
    try:
        return app.media.submit(
            resource_id=(body or {}).get("resource_id", ""),
            filename=(body or {}).get("filename", ""),
            kind=(body or {}).get("kind", "audio"),
            media_type=(body or {}).get("media_type", ""),
            size_bytes=int((body or {}).get("size_bytes", 0)),
        ).model_dump(mode="json")
    except DomainError as error:
        raise _map(error) from error


@router.get("/media")
async def list_media(request: Request):
    return [
        _app(request).media.get(m.media_job_id).model_dump(mode="json")
        for m in _app(request).media.list()
    ]


@router.get("/media/{media_job_id}")
async def get_media(request: Request, media_job_id: str):
    try:
        return _app(request).media.get(media_job_id).model_dump(mode="json")
    except DomainError as error:
        raise _map(error) from error


# --- tasks ------------------------------------------------------------------


@router.post("/tasks/{task_id}/resume")
async def resume_task(request: Request, task_id: str):
    try:
        await _app(request).resume(task_id)
        return {"task_id": task_id, "status": "queued"}
    except DomainError as error:
        raise _map(error) from error


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(request: Request, task_id: str):
    _app(request).request_cancel(task_id)
    return {"task_id": task_id, "status": "cancelling"}


# --- library ----------------------------------------------------------------


@router.get("/library")
async def library(request: Request):
    return _app(request).library.summary()
