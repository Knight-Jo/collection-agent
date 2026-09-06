"""Search settings API routes (spec 002 §6)."""

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
    }
    return HTTPException(mapping.get(error.code, 500), error.message)


@router.get("/search-sources")
async def search_sources(request: Request):
    return _app(request).search_settings.search_sources()


@router.post("/search-sources")
async def add_search_source(request: Request, body: dict):
    name = (body or {}).get("name", "").strip()
    url = (body or {}).get("url", "").strip()
    if not name or not url:
        raise HTTPException(422, "name and url are required")
    try:
        return _app(request).search_settings.add_search_source(name, url)
    except DomainError as error:
        raise _map(error) from error


@router.post("/search-sources/{source_id}/toggle")
async def toggle_search_source(request: Request, source_id: str):
    try:
        return _app(request).search_settings.toggle_search_source(source_id)
    except DomainError as error:
        raise _map(error) from error


@router.patch("/search-sources/{source_id}")
async def update_search_source(request: Request, source_id: str, body: dict):
    try:
        return _app(request).search_settings.update_search_source(
            source_id, body or {}
        )
    except DomainError as error:
        raise _map(error) from error


@router.get("/ai-search-tools")
async def ai_search_tools(request: Request):
    return _app(request).search_settings.ai_search_tools()


@router.post("/ai-search-tools/{tool_id}/toggle")
async def toggle_ai_search_tool(request: Request, tool_id: str):
    try:
        return _app(request).search_settings.toggle_ai_tool(tool_id)
    except DomainError as error:
        raise _map(error) from error


@router.patch("/ai-search-tools/{tool_id}/api-key")
async def update_ai_search_tool_key(
    request: Request, tool_id: str, body: dict
):
    api_key = (body or {}).get("api_key", "")
    try:
        return _app(request).search_settings.update_ai_tool_key(
            tool_id, api_key
        )
    except DomainError as error:
        raise _map(error) from error
