"""CLI entry: run an intelligence collection task.

Usage:
  python -m intel_agent --topic "低空经济投资进展" --questions "2026年低空经济融资规模" "头部企业商业化进展" "政策监管动态" \
      [--config config.yaml] [--max-sources 2 --max-quality 1 --recency 90 --require-recency]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartStartEvent,
    TextPart,
)

from .config import load_config
from .models import ResearchScope, SufficiencyCriteria
from .runner import TaskRunSpec, run_agent_task
from .task import load_task


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="OSINT collection agent (pydantic-ai port)"
    )
    parser.add_argument("--topic", required=True, help="情报收集主题")
    parser.add_argument(
        "--questions",
        nargs="*",
        default=[],
        help="可选的关键问题（最多 6 个）",
    )
    parser.add_argument("--objective", default="", help="调研目标")
    parser.add_argument("--time-range", default="", help="调研时间范围")
    parser.add_argument(
        "--geography", nargs="*", default=[], help="调研地区范围"
    )
    parser.add_argument("--language", nargs="*", default=[], help="检索语言")
    parser.add_argument(
        "--report-depth",
        choices=("brief", "standard", "deep"),
        default="standard",
        help="报告详略程度",
    )
    parser.add_argument("--config", default=None, help="config.yaml 路径")
    parser.add_argument(
        "--cwd", default=".", help="工作目录（data/intel 等相对此目录）"
    )
    parser.add_argument(
        "--min-sources", type=int, default=2, help="每个问题最少独立来源组"
    )
    parser.add_argument(
        "--min-quality", type=int, default=1, help="每个问题最少高质量来源组"
    )
    parser.add_argument(
        "--recency", type=int, default=90, help="时效窗口（天）"
    )
    parser.add_argument(
        "--require-recency", action="store_true", help="强制时效要求"
    )
    parser.add_argument(
        "--deep-crawl",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="启用深度抓取（省略时使用配置默认值）",
    )
    parser.add_argument(
        "--max-turns", type=int, default=40, help="agent 最大工具轮次"
    )
    parser.add_argument(
        "--max-tool-calls", type=int, default=None, help="agent 最大工具调用数"
    )
    parser.add_argument(
        "--trace", default=None, help="保存完整消息轨迹到 JSONL 文件"
    )
    return parser


def _msg_to_json(value):
    """Recursively convert dataclass/pydantic message objects to JSON-safe structures."""
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump(mode="json")
        except Exception:
            pass
    if hasattr(value, "__dataclass_fields__"):
        return {
            k: _msg_to_json(getattr(value, k))
            for k in value.__dataclass_fields__
        }
    if isinstance(value, dict):
        return {k: _msg_to_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_msg_to_json(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


_SENSITIVE_KEY_RE = re.compile(
    r"key|token|authorization|cookie|secret|password", re.IGNORECASE
)


def _redact(value):
    """Drop credential-like keys from tool arguments before tracing."""
    if isinstance(value, dict):
        return {
            key: _redact(item)
            for key, item in value.items()
            if not _SENSITIVE_KEY_RE.search(str(key))
        }
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    return value


class _TraceWriter:
    """Append one JSON object per line; the file survives abrupt exits."""

    def __init__(self, path: str):
        # Held open for the whole run so every event is flushed to disk
        # immediately; closing early would drop the tail on abrupt exits.
        self._stream = Path(path).open(  # noqa: SIM115
            "w", encoding="utf-8"
        )

    def event(self, kind: str, data: dict) -> None:
        line = {"type": kind, **data}
        self._stream.write(
            json.dumps(line, ensure_ascii=False, default=_msg_to_json) + "\n"
        )
        self._stream.flush()

    def close(self) -> None:
        self._stream.close()


def _trace_event_line(event: object) -> tuple[str, dict] | None:
    if isinstance(event, FunctionToolCallEvent):
        return (
            "tool_call",
            {
                "tool": event.part.tool_name,
                "tool_call_id": event.tool_call_id,
                "args": _redact(event.part.args),
            },
        )
    if isinstance(event, FunctionToolResultEvent):
        return (
            "tool_result",
            {
                "tool": event.part.tool_name,
                "tool_call_id": event.tool_call_id,
            },
        )
    if isinstance(event, PartStartEvent) and isinstance(event.part, TextPart):
        return ("model_response", {})
    return None


def _write_usage(writer: _TraceWriter, usage) -> None:
    writer.event(
        "usage",
        {
            "requests": usage.requests,
            "tool_calls": usage.tool_calls,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "total_tokens": usage.total_tokens,
        },
    )


async def _run_trace(args, settings, spec):
    """Run the task while incrementally persisting trace events to JSONL."""
    writer = _TraceWriter(args.trace) if args.trace else None

    async def on_event(event: object) -> None:
        line = _trace_event_line(event)
        if writer is not None and line is not None:
            writer.event(*line)

    try:
        result = await run_agent_task(
            Path(args.cwd), settings, spec, on_event=on_event
        )
    except BaseException:
        if writer is not None:
            writer.event("terminated", {"reason": "aborted"})
        raise
    else:
        if writer is not None:
            _write_usage(writer, result.usage)
    finally:
        if writer is not None:
            writer.close()
    return result


async def _run(args: argparse.Namespace) -> int:
    settings = load_config(args.config)
    if not settings.model_api_key():
        print(
            f"错误: 缺少模型 API key，请设置环境变量 {settings.model.api_key_env}",
            file=sys.stderr,
        )
        return 1
    spec = TaskRunSpec(
        topic=args.topic,
        objective=args.objective,
        questions=args.questions,
        scope=ResearchScope(
            time_range=args.time_range,
            geography=args.geography,
            languages=args.language,
        ),
        report_depth=args.report_depth,
        criteria=SufficiencyCriteria(
            min_independent_sources=args.min_sources,
            min_high_quality_sources=args.min_quality,
            recency_days=args.recency,
            require_recency=args.require_recency,
        ),
        deep_crawl=args.deep_crawl,
        max_requests=args.max_turns,
        max_tool_calls=args.max_tool_calls,
    )
    result = await _run_trace(args, settings, spec)
    print(result.output)
    usage = result.usage
    print(
        f"\n[usage] requests={usage.requests} total_tokens={usage.total_tokens}"
    )
    try:
        task = load_task(Path(args.cwd))
    except Exception:
        return 2
    return 0 if task.stage == "done" else 2


def main() -> int:
    args = _build_parser().parse_args()
    if len(args.questions) > 6:
        print("错误: questions 数量不能超过 6 个", file=sys.stderr)
        return 1
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
