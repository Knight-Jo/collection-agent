"""HTML extraction backend tests (T07)."""

from __future__ import annotations

from pathlib import Path

import pytest

from intel_agent.extraction.backends.html import (
    BeautifulSoupBackend,
    TrafilaturaBackend,
)
from intel_agent.extraction.registry import BackendRegistry
from intel_agent.extraction.service import (
    ExtractionProfile,
    ExtractionService,
)
from intel_agent.runtime.config import ExtractionConfig
from intel_agent.runtime.execution import Executor

FIXTURES = Path(__file__).parent.parent / "fixtures" / "html"


@pytest.fixture
def html_service(resource_store):
    registry = BackendRegistry()
    registry.register("trafilatura", TrafilaturaBackend(resource_store))
    registry.register("beautifulsoup", BeautifulSoupBackend(resource_store))
    service = ExtractionService(
        registry, resource_store, Executor(), ExtractionConfig()
    )
    for profile in service.default_profiles():
        service.register_profile(profile)
    service._import_fixture = _import_fixture
    return service


async def _import_fixture(resource_store, name: str):
    path = FIXTURES / name
    from datetime import UTC, datetime

    from intel_agent.contracts.resources import ResourceOrigin

    async def chunks():
        with path.open("rb") as fh:
            while chunk := fh.read(64 * 1024):
                yield chunk

    return await resource_store.write_stream(
        chunks(),
        origin=ResourceOrigin(acquired_at=datetime.now(UTC)),
        media_type="text/html",
    )


async def _extract_with_backend(html_service, name, backend_id):
    resource = await _import_fixture(html_service.resource_store, name)
    profile = ExtractionProfile(
        name="html", media_type="text/html", preferred=backend_id
    )
    pid = html_service.register_profile(profile)
    return await html_service.extract(resource, pid)


@pytest.mark.parametrize("backend_id", ["trafilatura", "beautifulsoup"])
async def test_both_html_backends_keep_order(html_service, backend_id):
    result = await _extract_with_backend(
        html_service, "article-zh.html", backend_id
    )
    paragraphs = [
        block.text
        for block in result.blocks
        if block.block_type == "paragraph"
    ]
    assert paragraphs == [
        "项目于2025年启动。",
        "第一阶段覆盖三个城市。",
        "下一阶段计划扩展测试。",
    ]


async def test_backend_fallback_selects_one_complete_artifact(html_service):
    # A profile with trafilatura preferred and bs4 fallback yields one
    # complete artifact, not a concatenation.
    resource = await _import_fixture(
        html_service.resource_store, "article-zh.html"
    )
    profile = ExtractionProfile(
        name="html",
        media_type="text/html",
        preferred="trafilatura",
        fallback="beautifulsoup",
    )
    pid = html_service.register_profile(profile)
    result = await html_service.extract(resource, pid)
    assert result.status == "success"
    texts = [b.text for b in result.blocks]
    assert texts.count("项目于2025年启动。") == 1
