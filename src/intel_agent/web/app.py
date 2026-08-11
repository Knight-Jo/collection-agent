"""FastAPI application for the local intelligence research workbench."""

from __future__ import annotations

import argparse
import json
from importlib.util import find_spec
from pathlib import Path
from shutil import which
from typing import Literal
from urllib.parse import urlparse

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from ..config import Settings, load_config
from ..models import IntelError
from .runs import RunRegistry
from .schemas import (
    ArtifactView,
    CrawlStatus,
    ProcessorStatus,
    RunCreate,
    RunView,
    ServiceStatus,
    SystemStatus,
    TaskSummary,
    TaskView,
)
from .views import (
    get_artifact,
    get_resource_download,
    get_task_view,
    list_task_summaries,
)


def create_app(
    *,
    cwd: Path,
    settings: Settings,
    registry: RunRegistry | None = None,
    static_dir: Path | None = None,
) -> FastAPI:
    """Create an app bound to one workspace and one in-memory run registry."""
    app = FastAPI(title="Intel Agent Workbench", version="0.1.0")
    app.state.cwd = cwd.resolve()
    app.state.settings = settings
    app.state.registry = registry or RunRegistry(app.state.cwd, settings)

    @app.exception_handler(IntelError)
    async def handle_intel_error(
        _request: Request, error: IntelError
    ) -> JSONResponse:
        status = {
            "NOT_FOUND": 404,
            "RUN_ALREADY_ACTIVE": 409,
            "OUTPUT_TAMPERED": 409,
            "DOCUMENT_TAMPERED": 409,
            "MODEL_NOT_CONFIGURED": 503,
            "INVALID_INPUT": 422,
        }.get(error.code, 400)
        return JSONResponse(
            status_code=status,
            content={"error": {"code": error.code, "message": str(error)}},
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request, error: RequestValidationError
    ) -> JSONResponse:
        message = "; ".join(str(item["msg"]) for item in error.errors())
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "INVALID_INPUT", "message": message}},
        )

    @app.get("/api/system", response_model=SystemStatus)
    async def system_status() -> SystemStatus:
        audit = settings.audit_model or settings.model
        return SystemStatus(
            model=ServiceStatus(
                name=settings.model.name,
                configured=bool(settings.model_api_key()),
            ),
            audit=ServiceStatus(
                name=audit.name,
                configured=bool(settings.audit_api_key()),
            ),
            search=ServiceStatus(
                name="SearXNG",
                configured=bool(settings.search.searxng_url),
            ),
            crawl=CrawlStatus(
                default_enabled=settings.crawl.enabled_by_default
            ),
            processors=ProcessorStatus(
                tesseract=bool(
                    which("tesseract") and find_spec("pytesseract")
                ),
                ffmpeg=which("ffmpeg") is not None,
                whisper=find_spec("faster_whisper") is not None,
                libreoffice=which("libreoffice") is not None,
            ),
        )

    @app.get("/api/tasks", response_model=list[TaskSummary])
    async def tasks() -> list[TaskSummary]:
        return list_task_summaries(app.state.cwd)

    @app.get("/api/tasks/{task_id}", response_model=TaskView)
    async def task_detail(task_id: str) -> TaskView:
        return get_task_view(app.state.cwd, task_id)

    @app.get("/api/tasks/{task_id}/resources/{document_id}/download")
    async def resource_download(
        task_id: str, document_id: str
    ) -> FileResponse:
        path, document = get_resource_download(
            app.state.cwd, task_id, document_id
        )
        filename = Path(urlparse(document.final_url).path).name or document.id
        return FileResponse(
            path,
            media_type=document.content_type,
            filename=filename,
            headers={"X-Content-Type-Options": "nosniff"},
        )

    @app.get(
        "/api/tasks/{task_id}/artifacts/{kind}", response_model=ArtifactView
    )
    async def artifact(
        task_id: str, kind: Literal["assessment", "package"]
    ) -> ArtifactView:
        return get_artifact(app.state.cwd, task_id, kind)

    @app.post("/api/runs", response_model=RunView, status_code=202)
    async def create_run(request: RunCreate) -> RunView:
        if not settings.model_api_key():
            raise IntelError(
                "MODEL_NOT_CONFIGURED",
                f"缺少模型 API key，请设置环境变量 {settings.model.api_key_env}",
            )
        return await app.state.registry.create(request.to_spec())

    @app.get("/api/runs/{run_id}", response_model=RunView)
    async def run_detail(run_id: str) -> RunView:
        return app.state.registry.get(run_id)

    @app.post("/api/runs/{run_id}/cancel", response_model=RunView)
    async def cancel_run(run_id: str) -> RunView:
        return app.state.registry.cancel(run_id)

    @app.get("/api/runs/{run_id}/events")
    async def run_events(request: Request, run_id: str) -> StreamingResponse:
        app.state.registry.get(run_id)
        header = request.headers.get("last-event-id", "0")
        try:
            after_id = int(header)
        except ValueError:
            after_id = 0

        async def stream():
            async for event in app.state.registry.subscribe(run_id, after_id):
                if event is None:
                    yield ": heartbeat\n\n"
                    continue
                data = json.dumps(event.data, ensure_ascii=False)
                yield f"id: {event.id}\nevent: {event.type}\ndata: {data}\n\n"

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    frontend = (
        static_dir or Path(__file__).resolve().parents[3] / "web" / "dist"
    )
    if frontend.exists():
        assets = frontend / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def frontend_route(path: str) -> FileResponse:
            return FileResponse(frontend / "index.html")

    return app


def main() -> None:
    """Run the local workbench server."""
    parser = argparse.ArgumentParser(
        description="Intel Agent local Web workbench"
    )
    parser.add_argument("--cwd", default=".")
    parser.add_argument("--config", default=None)
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()
    settings = load_config(args.config)
    uvicorn.run(
        create_app(cwd=Path(args.cwd), settings=settings),
        host=args.host if args.host is not None else settings.web.host,
        port=args.port if args.port is not None else settings.web.port,
    )
