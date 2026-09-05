"""In-process event bus for streaming agent events to SSE subscribers."""

from __future__ import annotations

import asyncio
from collections import defaultdict


class EventBus:
    """Fan-out of JSON events to per-conversation subscriber queues."""

    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)

    def subscribe(self, key: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers[key].add(queue)
        return queue

    def unsubscribe(self, key: str, queue: asyncio.Queue) -> None:
        self._subscribers.get(key, set()).discard(queue)
        if not self._subscribers[key]:
            del self._subscribers[key]

    def publish(self, key: str, event: dict) -> None:
        for queue in list(self._subscribers.get(key, ())):
            queue.put_nowait(event)
