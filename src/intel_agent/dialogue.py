"""Tool-free dialogue over task-scoped retrieved passages."""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable, Sequence
from typing import Literal, Protocol, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic_ai import Agent
from pydantic_core import from_json

from .agent import _bounded_model_settings, _build_chat_model
from .config import Settings
from .models import ActionType, IntelError, IntelTask, Message
from .retrieval import RetrievedPassage

DIALOGUE_SYSTEM_PROMPT = """\
你是公开信息调研任务的对话助手。你只能依据输入中的任务状态和候选材料回答，
不得使用外部知识，不得联网，不得编造来源、URL、引文或材料编号。

只返回一个 JSON 对象，字段如下：
intent, answer, answerability, cited_passage_ids, gaps, action。
intent 只能是 greeting、ask_evidence、ask_task_status、ask_methodology、
continue_research、search_gap、search_specific_topic、generate_report 或
regenerate_report。普通问候使用 greeting，且 action 必须为 null。
answerability 只能是 answered、partial、not_answerable。
action 可为 null；非空时包含 type、request_mode、scope。
仅当用户明确命令继续搜索或生成报告时使用 explicit_message；疑问、建议、
假设或含否定的表达只能使用 proposed。引用只能填写输入中的 passage id。
"""


class DialogueAction(BaseModel):
    """One task action inferred from a dialogue turn."""

    model_config = ConfigDict(extra="forbid")

    type: ActionType
    request_mode: Literal["explicit_message", "proposed"]
    scope: dict[str, object] = Field(default_factory=dict)


class DialogueDecision(BaseModel):
    """Validated answer and optional task action returned by dialogue."""

    model_config = ConfigDict(extra="forbid")

    intent: Literal[
        "greeting",
        "ask_evidence",
        "ask_task_status",
        "ask_methodology",
        "continue_research",
        "search_gap",
        "search_specific_topic",
        "generate_report",
        "regenerate_report",
    ]
    answer: str = Field(min_length=1)
    answerability: Literal["answered", "partial", "not_answerable"]
    cited_passage_ids: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    action: DialogueAction | None = None


class _RunResult(Protocol):
    output: str


class _DialogueAgent(Protocol):
    async def run(self, prompt: str) -> _RunResult: ...


def build_dialogue_prompt(
    task: IntelTask,
    summary: str,
    messages: Sequence[Message],
    passages: Sequence[RetrievedPassage],
    run_status: str,
) -> str:
    """Build a bounded prompt from the active task conversation only."""
    task_snapshot = {
        "id": task.id,
        "topic": task.topic,
        "objective": task.objective,
        "stage": task.stage,
        "completion_status": task.completion_status,
        "questions": [item.model_dump() for item in task.questions],
        "research_run_status": run_status,
    }
    recent_messages = [
        {
            "role": message.role,
            "content": _clip(message.content, 2_000),
        }
        for message in messages[-10:]
    ]
    passage_values = [
        {
            "id": passage.id,
            "kind": passage.citation_kind,
            "title": passage.title,
            "quote": _clip(passage.quote_text, 4_000),
        }
        for passage in passages[:8]
    ]
    return "\n\n".join(
        (
            "<task_snapshot>\n"
            + json.dumps(task_snapshot, ensure_ascii=False)
            + "\n</task_snapshot>",
            f"<conversation_summary>\n{_clip(summary, 4_000)}\n"
            "</conversation_summary>",
            "<recent_messages>\n"
            + json.dumps(recent_messages, ensure_ascii=False)
            + "\n</recent_messages>",
            "<retrieved_passages>\n"
            + json.dumps(passage_values, ensure_ascii=False)
            + "\n</retrieved_passages>",
        )
    )


class DialogueEngine:
    """Make one bounded, tool-free model decision for a conversation turn."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        agent: _DialogueAgent | None = None,
    ):
        settings = settings or Settings()
        if agent is None:
            built = Agent(
                _build_chat_model(settings.model, settings.model_api_key()),
                system_prompt=DIALOGUE_SYSTEM_PROMPT,
                model_settings=_bounded_model_settings(
                    settings.context,
                    min(settings.context.main_output_tokens, 2_048),
                ),
                name="dialogue-agent",
                retries=1,
            )
            agent = cast(_DialogueAgent, built)
        self.agent = agent

    async def answer(
        self,
        *,
        task: IntelTask,
        query: str,
        summary: str,
        messages: Sequence[Message],
        passages: Sequence[RetrievedPassage],
        run_status: str,
        on_delta: Callable[[str], Awaitable[None]] | None = None,
    ) -> DialogueDecision:
        """Return a validated decision with server-filtered citation IDs."""
        prompt = build_dialogue_prompt(
            task, summary, messages, passages, run_status
        )
        raw = (
            await self._stream_answer(prompt, on_delta)
            if on_delta is not None
            else (await self.agent.run(prompt)).output
        )
        try:
            decision = _parse_decision(raw)
        except (
            ValueError,
            ValidationError,
            json.JSONDecodeError,
        ) as error:
            schema = json.dumps(
                DialogueDecision.model_json_schema(), ensure_ascii=False
            )
            details = (
                json.dumps(error.errors(), ensure_ascii=False, default=str)
                if isinstance(error, ValidationError)
                else str(error)
            )
            repair = (
                "按照以下 JSON Schema 和校验错误修复原始输出。"
                "只返回单个 JSON 对象，不要解释。\n"
                f"JSON Schema:\n{schema}\n"
                f"校验错误:\n{details}\n"
                f"原始输出:\n{_clip(raw, 8_000)}"
            )
            repaired = (await self.agent.run(repair)).output
            try:
                decision = _parse_decision(repaired)
            except (
                ValueError,
                ValidationError,
                json.JSONDecodeError,
            ) as error:
                raise IntelError(
                    "DIALOGUE_FAILED", "对话模型未返回有效结构"
                ) from error

        allowed_ids = {passage.id for passage in passages[:8]}
        cited_ids = list(
            dict.fromkeys(
                item
                for item in decision.cited_passage_ids
                if item in allowed_ids
            )
        )
        action = decision.action
        if (
            action is not None
            and action.request_mode == "explicit_message"
            and not _is_explicit_action_request(query, action.type)
        ):
            action = action.model_copy(update={"request_mode": "proposed"})
        return decision.model_copy(
            update={"cited_passage_ids": cited_ids, "action": action}
        )

    async def _stream_answer(
        self,
        prompt: str,
        on_delta: Callable[[str], Awaitable[None]],
    ) -> str:
        raw = ""
        previous = ""
        async with cast(Agent, self.agent).run_stream(prompt) as result:
            async for chunk in result.stream_text(delta=True, debounce_by=0.1):
                raw += chunk
                current = _partial_answer(raw)
                if current.startswith(previous):
                    delta = current[len(previous) :]
                    if delta:
                        await on_delta(delta)
                        previous = current
        return raw

    async def summarize(self, messages: Sequence[Message]) -> str:
        """Compact older visible messages for the next bounded prompt."""
        transcript = [
            {"role": item.role, "content": _clip(item.content, 2_000)}
            for item in messages
        ]
        prompt = (
            "请用不超过 800 个汉字概括以下对话中已确认结论、未解决缺口和用户明确要求。"
            "不要添加新事实：\n" + json.dumps(transcript, ensure_ascii=False)
        )
        return _clip((await self.agent.run(prompt)).output.strip(), 4_000)


def _parse_decision(raw: str) -> DialogueDecision:
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
        raise ValueError("dialogue response must be an object")
    return DialogueDecision.model_validate(parsed)


def _partial_answer(raw: str) -> str:
    start = raw.find("{")
    if start < 0:
        return ""
    try:
        parsed = from_json(raw[start:], allow_partial="trailing-strings")
    except ValueError:
        return ""
    if isinstance(parsed, dict) and isinstance(parsed.get("answer"), str):
        return parsed["answer"]
    return ""


def _is_explicit_action_request(query: str, action_type: ActionType) -> bool:
    normalized = query.casefold().strip()
    ambiguous = ("?", "？", "吗", "是否", "有没有必要", "不要", "不用", "别")
    if any(marker in normalized for marker in ambiguous):
        return False
    if action_type in {"generate_report", "regenerate_report"}:
        markers = ("生成报告", "重新生成报告", "更新报告", "generate report")
    else:
        markers = (
            "继续搜索",
            "继续搜",
            "再搜",
            "补充检索",
            "继续调研",
            "search for",
            "continue research",
        )
    return any(marker in normalized for marker in markers)


def _clip(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[:limit] + "…"
