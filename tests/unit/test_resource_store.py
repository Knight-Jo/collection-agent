"""ResourceStore streaming and limit tests (T02)."""

from __future__ import annotations

import asyncio

import pytest

from intel_agent.contracts.errors import DomainError
from intel_agent.contracts.resources import ResourceOrigin
from datetime import UTC, datetime


async def _chunks(payload: bytes, step: int = 3):
    for i in range(0, len(payload), step):
        yield payload[i : i + step]


def test_write_stream_shares_blob_for_identical_bytes(resource_store):
    async def run():
        origin = ResourceOrigin(acquired_at=datetime.now(UTC))
        a = await resource_store.write_stream(
            _chunks(b"same bytes"), origin=origin,
            media_type="text/plain",
        )
        b = await resource_store.write_stream(
            _chunks(b"same bytes"), origin=origin,
            media_type="text/plain",
        )
        assert a.content_hash == b.content_hash
        assert a.resource_id != b.resource_id
        return a, b

    a, b = asyncio.run(run())
    assert a.content_ref == b.content_ref


def test_write_stream_enforces_max_bytes(resource_store):
    async def run():
        origin = ResourceOrigin(acquired_at=datetime.now(UTC))
        with pytest.raises(DomainError) as raised:
            await resource_store.write_stream(
                _chunks(b"x" * 100), origin=origin,
                media_type="text/plain", max_bytes=10,
            )
        return raised.value

    error = asyncio.run(run())
    assert error.code == "TOO_LARGE"
