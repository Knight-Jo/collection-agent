"""Tool-free intake classification for Conversation-first research."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Literal, Protocol, Self, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)
from pydantic_ai import Agent

from .agent import _bounded_model_settings, _build_chat_model
from .config import Settings
from .models import IntelError, Message, ResearchBrief

INTAKE_SYSTEM_PROMPT = """\
你是公开信息调研系统的接待助手，不得调用工具或联网。判断用户是在询问系统能力、
需要补充调研范围，还是已给出可执行的调研请求。只返回 JSON：intent、reply、
research_brief、missing_fields。intent 只能是 capability_query、clarify_research、
start_research。start_research 必须提供包含 topic、objective、key_questions、scope、
entities、constraints、requested_outputs 的 research_brief，关键问题为 2 至 6 个。
"""


class IntakeDecision(BaseModel):
    """Validated outcome of one intake conversation turn."""

    model_config = ConfigDict(extra="forbid")

    intent: Literal["capability_query", "clarify_research", "start_research"]
    reply: str = Field(min_length=1)
    research_brief: ResearchBrief | None = None
    missing_fields: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_brief(self) -> Self:
        if self.intent == "start_research" and self.research_brief is None:
            raise ValueError("start_research requires research_brief")
        return self


class _RunResult(Protocol):
    output: str


class _IntakeAgent(Protocol):
    async def run(self, prompt: str) -> _RunResult: ...


class IntakeEngine:
    """Classify intake turns with a bounded model and no tools."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        agent: _IntakeAgent | None = None,
    ):
        settings = settings or Settings()
        if agent is None:
            built = Agent(
                _build_chat_model(settings.model, settings.model_api_key()),
                system_prompt=INTAKE_SYSTEM_PROMPT,
                model_settings=_bounded_model_settings(
                    settings.context, 1_024
                ),
                name="intake-agent",
                retries=1,
            )
            agent = cast(_IntakeAgent, built)
        self.agent = agent

    async def decide(
        self, query: str, messages: Sequence[Message]
    ) -> IntakeDecision:
        """Return one structured intake decision, repairing JSON once."""
        recent = [
            {"role": item.role, "content": item.content[:2_000]}
            for item in messages[-8:]
        ]
        prompt = json.dumps(
            {"recent_messages": recent, "user_message": query},
            ensure_ascii=False,
        )
        raw = (await self.agent.run(prompt)).output
        try:
            return _parse_decision(raw)
        except (ValueError, ValidationError, json.JSONDecodeError):
            repaired = (
                await self.agent.run(
                    "修复为协议要求的单个 JSON 对象，只返回 JSON：\n"
                    + raw[:8_000]
                )
            ).output
            try:
                return _parse_decision(repaired)
            except (
                ValueError,
                ValidationError,
                json.JSONDecodeError,
            ) as error:
                raise IntelError(
                    "INTAKE_FAILED", "接待模型未返回有效结构"
                ) from error


def _parse_decision(raw: str) -> IntakeDecision:
    value = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", value, re.DOTALL)
    if fenced:
        value = fenced.group(1).strip()
    else:
        start = value.find("{")
        end = value.rfind("}")
        if start >= 0 and end >= start:
            value = value[start : end + 1]
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("intake response must be an object")
    return IntakeDecision.model_validate(parsed)
