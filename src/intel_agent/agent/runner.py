"""Streaming agent runner: one seam for every role invocation.

Structured-output agents cannot use ``stream_text`` (tool-call responses),
so progress rides on ``stream_response`` events and the validated object
comes from ``get_output`` once the stream completes. Agents without
``run_stream`` (test fakes, plain runners) fall back to ``run``.

Streaming changes the timeout contract: the HTTP read timeout now bounds
the gap between chunks, not the whole generation, so a healthy long
generation never times out while a dead endpoint is detected within one
read-timeout window.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any, NamedTuple

ProgressCallback = Callable[[int], Any]


class RunOutcome(NamedTuple):
    """Uniform result of a role call: validated output plus token usage."""

    output: Any
    usage: Any


async def run_agent(
    agent: Any,
    prompt: str,
    *,
    on_progress: ProgressCallback | None = None,
) -> RunOutcome:
    """Run a role agent and return its validated structured output.

    ``on_progress`` receives the running count of stream events (roughly
    token deltas); sync and async callbacks are both accepted, letting
    callers surface heartbeat progress without interpreting stream content.
    """
    run_stream = getattr(agent, "run_stream", None)
    if run_stream is None:
        result = await agent.run(prompt)
        return RunOutcome(
            output=result.output, usage=getattr(result, "usage", None)
        )

    events = 0
    async with agent.run_stream(prompt) as result:
        async for _ in result.stream_response():
            events += 1
            if on_progress is not None:
                awaited = on_progress(events)
                if inspect.isawaitable(awaited):
                    await awaited
        output = await result.get_output()
        return RunOutcome(output=output, usage=getattr(result, "usage", None))


__all__ = ["run_agent", "RunOutcome", "ProgressCallback"]
