"""Streaming agent runner tests."""

from __future__ import annotations

from types import SimpleNamespace

from intel_agent.agent.runner import RunOutcome, run_agent


class StreamingAgent:
    """Mimics pydantic-ai's run_stream contract for structured output."""

    def __init__(self, output, events: int = 3, usage=None) -> None:
        self._output = output
        self._events = events
        self._usage = usage or SimpleNamespace(
            requests=1, input_tokens=10, output_tokens=20
        )

    def run_stream(self, prompt):
        agent = self

        class _Result:
            async def stream_response(self):
                for _ in range(agent._events):
                    yield SimpleNamespace()

            async def get_output(self):
                return agent._output

            @property
            def usage(self):
                return agent._usage

        class _Ctx:
            async def __aenter__(self):
                return _Result()

            async def __aexit__(self, *exc):
                return False

        return _Ctx()


class PlainAgent:
    """Test-fake style agent: only run(), like FakeRole."""

    def __init__(self, output) -> None:
        self._output = output

    async def run(self, prompt):
        return SimpleNamespace(output=self._output)


async def test_streaming_agent_returns_output_and_usage():
    agent = StreamingAgent(output={"plan": 1})
    seen: list[int] = []
    outcome = await run_agent(
        agent, "prompt", on_progress=lambda events: seen.append(events)
    )
    assert isinstance(outcome, RunOutcome)
    assert outcome.output == {"plan": 1}
    assert outcome.usage.requests == 1
    assert seen == [1, 2, 3]  # one callback per stream event


async def test_streaming_agent_supports_async_progress_callback():
    agent = StreamingAgent(output="x", events=2)
    seen: list[int] = []

    async def progress(events: int) -> None:
        seen.append(events)

    outcome = await run_agent(agent, "p", on_progress=progress)
    assert outcome.output == "x"
    assert seen == [1, 2]


async def test_plain_agent_falls_back_to_run():
    agent = PlainAgent(output={"legacy": True})
    outcome = await run_agent(agent, "p")
    assert outcome.output == {"legacy": True}
    assert outcome.usage is None


async def test_streaming_without_progress_callback():
    agent = StreamingAgent(output=42)
    outcome = await run_agent(agent, "p")
    assert outcome.output == 42


class BrokenStreamAgent:
    """Stream validates fine structurally but the model JSON is truncated."""

    def __init__(self, recovered_output) -> None:
        self._recovered = recovered_output
        self.ran_non_streamed = False

    async def run(self, prompt):
        self.ran_non_streamed = True
        return SimpleNamespace(output=self._recovered)

    def run_stream(self, prompt):
        class _Result:
            async def stream_response(self):
                yield SimpleNamespace()

            async def get_output(self):
                from pydantic_ai.exceptions import UnexpectedModelBehavior

                raise UnexpectedModelBehavior(
                    "Output validation failed during streaming, "
                    "and retries are not supported in `run_stream()`"
                )

        class _Ctx:
            async def __aenter__(self):
                return _Result()

            async def __aexit__(self, *exc):
                return False

        return _Ctx()


async def test_validation_failure_falls_back_to_run_retry():
    agent = BrokenStreamAgent(recovered_output={"plan": "recovered"})
    outcome = await run_agent(agent, "prompt")
    assert outcome.output == {"plan": "recovered"}
    assert agent.ran_non_streamed
