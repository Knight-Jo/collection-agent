"""Workspace API routes: monitors, fact checks, media, tasks (spec 002 §6)."""

from __future__ import annotations

import logging
import mimetypes
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from ...contracts.errors import DomainError
from ...contracts.resources import ResourceOrigin
from ...monitoring.models import MonitorSchedule

router = APIRouter()


logger = logging.getLogger("intel_agent.api")


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
    logger.warning("api error code=%s message=%s", error.code, error.message)
    return HTTPException(mapping.get(error.code, 500), error.message)


# --- monitors ---------------------------------------------------------------


@router.post("/monitors")
async def create_monitor(request: Request, body: dict):
    app = _app(request)
    try:
        schedule = MonitorSchedule.model_validate(
            (body or {}).get("schedule") or {}
        )
        return app.monitoring.create_monitor(
            name=(body or {}).get("name", "").strip(),
            subject=(body or {}).get("subject", "").strip(),
            strategy=(body or {}).get("strategy", "").strip(),
            schedule=schedule,
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


@router.post("/monitors/{monitor_id}/toggle")
async def toggle_monitor(request: Request, monitor_id: str):
    try:
        return (
            _app(request).monitoring.toggle(monitor_id).model_dump(mode="json")
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
async def upload_media(request: Request, file: Annotated[UploadFile, File()]):
    app = _app(request)
    filename = file.filename or "upload"
    media_type = file.content_type or ""
    if not media_type or media_type == "application/octet-stream":
        media_type = (
            mimetypes.guess_type(filename)[0] or "application/octet-stream"
        )
    kind = "audio" if media_type.startswith("audio/") else "video"

    async def chunks():
        while True:
            chunk = await file.read(65536)
            if not chunk:
                break
            yield chunk

    try:
        resource = await app.resource_store.write_stream(
            chunks(),
            origin=ResourceOrigin(
                local_display_name=filename,
                acquired_at=datetime.now(UTC),
            ),
            media_type=media_type,
        )
        job = app.media.submit(
            resource.resource_id,
            filename,
            kind,
            media_type,
            resource.byte_length,
        )
        return job.model_dump(mode="json")
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
