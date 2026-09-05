"""Event bus fan-out tests."""

from __future__ import annotations

import asyncio

from intel_agent.runtime.events import EventBus


async def test_publish_delivers_to_subscriber():
    bus = EventBus()
    queue = bus.subscribe("conv-1")
    bus.publish("conv-1", {"type": "run.status", "status": "running"})
    event = await asyncio.wait_for(queue.get(), timeout=1)
    assert event == {"type": "run.status", "status": "running"}
    bus.unsubscribe("conv-1", queue)


async def test_publish_is_isolated_per_key():
    bus = EventBus()
    queue = bus.subscribe("conv-1")
    bus.publish("conv-2", {"type": "refetch"})
    with __import__("pytest").raises(asyncio.TimeoutError):
        await asyncio.wait_for(queue.get(), timeout=0.1)
    bus.unsubscribe("conv-1", queue)
