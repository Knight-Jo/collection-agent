"""FastAPI entry: research conversation surface (spec §16.1, §3.1)."""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..bootstrap import bootstrap
from ..contracts.errors import DomainError
from ..runtime.config import load_settings


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


def _sse(event: dict) -> str:
    etype = event.get("type", "message")
    data = json.dumps(event, ensure_ascii=False)
    return f"event: {etype}\ndata: {data}\n\n"


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

    # --- conversations ------------------------------------------------------

    @app.get("/api/conversations")
    async def list_conversations(request: Request, archived: bool = False):
        return _app(request).conversations.list_conversations(archived)

    @app.post("/api/conversations")
    async def create_conversation(request: Request):
        return _app(request).conversations.create_conversation()

    @app.post("/api/conversations/{conversation_id}/archive")
    async def archive_conversation(request: Request, conversation_id: str):
        return _app(request).conversations.archive(conversation_id)

    @app.post("/api/conversations/{conversation_id}/restore")
    async def restore_conversation(request: Request, conversation_id: str):
        return _app(request).conversations.restore(conversation_id)

    @app.get("/api/conversations/{conversation_id}")
    async def get_conversation(request: Request, conversation_id: str):
        try:
            return _app(request).conversations.projection(conversation_id)
        except DomainError as error:
            raise _map_error(error) from error

    @app.post("/api/conversations/{conversation_id}/messages")
    async def send_message(request: Request, conversation_id: str, body: dict):
        content = (body or {}).get("content", "").strip()
        if not content:
            raise HTTPException(422, "content is required")
        try:
            return await _app(request).conversations.send_message(
                conversation_id, content
            )
        except DomainError as error:
            raise _map_error(error) from error

    @app.get("/api/conversations/{conversation_id}/events")
    async def conversation_events(request: Request, conversation_id: str):
        application = _app(request)
        queue = application.events.subscribe(conversation_id)

        async def stream():
            try:
                yield _sse({"type": "refetch"})
                while True:
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=15)
                    except TimeoutError:
                        yield ": keepalive\n\n"
                        continue
                    yield _sse(event)
            finally:
                application.events.unsubscribe(conversation_id, queue)

        return StreamingResponse(stream(), media_type="text/event-stream")

    # --- brief and research start ------------------------------------------

    @app.post("/api/briefs/generate")
    async def generate_brief(request: Request, body: dict):
        prompt = (body or {}).get("prompt", "").strip()
        if not prompt:
            raise HTTPException(422, "prompt is required")
        return await _app(request).conversations.generate_brief(prompt)

    @app.post("/api/research/start")
    async def start_research(request: Request, body: dict):
        topic = (body or {}).get("topic", "").strip()
        brief = (body or {}).get("brief") or {}
        if not topic:
            raise HTTPException(422, "topic is required")
        return await _app(request).conversations.start_research(topic, brief)

    # --- system / library ---------------------------------------------------

    @app.get("/api/system")
    async def system(request: Request):
        return _app(request).conversations.system_status()

    @app.get("/api/library")
    async def library(request: Request):
        return _app(request).conversations.library()

    # --- search sources -----------------------------------------------------

    @app.get("/api/search-sources")
    async def search_sources(request: Request):
        return _app(request).conversations.search_sources()

    @app.post("/api/search-sources")
    async def add_search_source(request: Request, body: dict):
        raise HTTPException(501, "not implemented")

    @app.post("/api/search-sources/{source_id}/toggle")
    async def toggle_search_source(request: Request, source_id: str):
        raise HTTPException(501, "not implemented")

    @app.patch("/api/search-sources/{source_id}")
    async def update_search_source(
        request: Request, source_id: str, body: dict
    ):
        raise HTTPException(501, "not implemented")

    # --- ai search tools ----------------------------------------------------

    @app.get("/api/ai-search-tools")
    async def ai_search_tools(request: Request):
        return _app(request).conversations.ai_search_tools()

    @app.post("/api/ai-search-tools/{tool_id}/toggle")
    async def toggle_ai_search_tool(request: Request, tool_id: str):
        raise HTTPException(501, "not implemented")

    @app.patch("/api/ai-search-tools/{tool_id}/api-key")
    async def update_ai_search_tool_key(
        request: Request, tool_id: str, body: dict
    ):
        raise HTTPException(501, "not implemented")

    return app
