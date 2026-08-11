"""CLI entry: run an intelligence collection task.

Usage:
  python -m intel_agent --topic "低空经济投资进展" --questions "2026年低空经济融资规模" "头部企业商业化进展" "政策监管动态" \
      [--config config.yaml] [--max-sources 2 --max-quality 1 --recency 90 --require-recency]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .config import load_config
from .models import SufficiencyCriteria
from .runner import TaskRunSpec, run_agent_task


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="OSINT collection agent (pydantic-ai port)"
    )
    parser.add_argument("--topic", required=True, help="情报收集主题")
    parser.add_argument(
        "--questions", nargs="+", required=True, help="2-6 个关键问题"
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
        "--max-turns", type=int, default=40, help="agent 最大工具轮次"
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


def _write_trace(path: str, messages) -> None:
    events = []
    for msg in messages:
        for part in msg.parts:
            kind = type(part).__name__
            if kind == "ToolCallPart":
                events.append(
                    {
                        "type": "tool_call",
                        "tool": part.tool_name,
                        "args": part.args,
                    }
                )
            elif kind == "ToolReturnPart":
                events.append(
                    {
                        "type": "tool_result",
                        "tool": part.tool_name,
                        "tool_call_id": part.tool_call_id,
                    }
                )
            elif kind == "ModelRequestPart":
                events.append(
                    {"type": "model_request", "kind": type(part).__name__}
                )
    raw = [_msg_to_json(msg) for msg in messages]
    (Path(path)).write_text(
        json.dumps(
            {"events": events, "messages": raw}, ensure_ascii=False, indent=2
        ),
        encoding="utf-8",
    )


async def _run(args: argparse.Namespace) -> int:
    settings = load_config(args.config)
    if not settings.model_api_key():
        print(
            "错误: 缺少模型 API key，请设置环境变量 "
            + settings.model.api_key_env,
            file=sys.stderr,
        )
        return 1
    spec = TaskRunSpec(
        topic=args.topic,
        questions=args.questions,
        criteria=SufficiencyCriteria(
            min_independent_sources=args.min_sources,
            min_high_quality_sources=args.min_quality,
            recency_days=args.recency,
            require_recency=args.require_recency,
        ),
    )
    result = await run_agent_task(Path(args.cwd), settings, spec)
    if args.trace:
        _write_trace(args.trace, result.all_messages())
    print(result.output)
    usage = result.usage
    print(
        f"\n[usage] requests={usage.requests} total_tokens={usage.total_tokens}"
    )
    return 0


def main() -> int:
    args = _build_parser().parse_args()
    if not 2 <= len(args.questions) <= 6:
        print("错误: questions 数量必须为 2-6 个", file=sys.stderr)
        return 1
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
