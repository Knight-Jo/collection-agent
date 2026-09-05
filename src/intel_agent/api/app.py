"""FastAPI entry (spec §16.1, §3.1)."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, UploadFile

from ..bootstrap import bootstrap
from ..contracts.errors import DomainError
from ..runtime.config import load_settings

_SETTINGS_KEY = "settings"
_APP_KEY = "application"


def _app(request: Request):
    return request.app.state.application


def _map_error(error: DomainError) -> HTTPException:
    if error.code == "NOT_FOUND":
        return HTTPException(404, error.message)
    if error.code == "INVALID_REQUEST":
        return HTTPException(409, error.message)
    if error.code == "TOO_LARGE":
        return HTTPException(413, error.message)
    return HTTPException(500, error.message)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    settings = load_settings(os.environ.get("INTEL_AGENT_CONFIG"))
    async with bootstrap(settings) as application:
        app.state.application = application
        app.state.settings = settings
        yield


def create_app() -> FastAPI:
    app = FastAPI(title="research-agent", lifespan=_lifespan)

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/capabilities")
    async def capabilities(request: Request):
        return {"status": "configured"}

    @app.post("/api/tasks", status_code=202)
    async def create_task(request: Request, body: dict):
        question = (body or {}).get("question", "").strip()
        if not question:
            raise HTTPException(422, "question is required")
        task = _app(request).submit(question)
        return {"task_id": task.task_id}

    @app.get("/api/tasks")
    async def list_tasks(request: Request):
        return {"tasks": []}

    @app.get("/api/tasks/{task_id}")
    async def get_task(request: Request, task_id: str):
        try:
            task = _app(request).status(task_id)
        except DomainError as error:
            raise _map_error(error) from error
        return task.model_dump(mode="json")

    @app.get("/api/tasks/{task_id}/result")
    async def get_result(request: Request, task_id: str):
        try:
            result = await _app(request).wait(task_id)
        except DomainError as error:
            raise _map_error(error) from error
        return result.model_dump(mode="json")

    @app.post("/api/tasks/{task_id}/resume", status_code=202)
    async def resume_task(request: Request, task_id: str):
        try:
            task = _app(request).resume(task_id)
        except DomainError as error:
            raise _map_error(error) from error
        return {"task_id": task.task_id}

    @app.post("/api/tasks/{task_id}/cancel")
    async def cancel_task(request: Request, task_id: str):
        _app(request).cancel(task_id)
        return {"task_id": task_id, "status": "cancelling"}

    @app.post("/api/tasks/{task_id}/materials")
    async def upload_material(
        request: Request, task_id: str, file: UploadFile
    ):
        settings = request.app.state.settings
        tmp_dir = settings.tmp_root() / task_id
        tmp_dir.mkdir(parents=True, exist_ok=True)
        dest = tmp_dir / Path(file.filename or "upload").name
        data = await file.read()
        dest.write_bytes(data)
        application = _app(request)
        resource = await application.orchestrator.acquisition_pipeline.resource_store.import_file(
            dest
        )
        report = await application.orchestrator.acquisition_pipeline.acquire(
            task_id,
            resource,
            application.orchestrator.profile_id,
            index_after_store=True,
        )
        return report.model_dump(mode="json")

    @app.get("/api/tasks/{task_id}/materials")
    async def list_materials(request: Request, task_id: str):
        return {"materials": []}

    return app
