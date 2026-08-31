"""CLI entry: run an intelligence collection task.

Usage:
  python -m intel_agent --topic "低空经济投资进展" --questions "2026年低空经济融资规模" "头部企业商业化进展" "政策监管动态" \
      [--config config.yaml] [--max-sources 2 --max-quality 1 --recency 90 --require-recency]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from .config import load_config
from .logging import configure_logging
from .models import ResearchScope, SufficiencyCriteria
from .runner import TaskRunSpec, run_agent_task
from .task import load_task
from .trajectory import JsonlTrajectoryRecorder


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
    parser.add_argument(
        "--conversation",
        default=None,
        help="保存完整模型会话（每轮输入输出）到 JSON 文件",
    )
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default=None,
        help="日志级别（默认读取 config.yaml 的 logging.level）",
    )
    return parser


async def _run_trace(args, settings, spec):
    """Run the task while recording a structured run trajectory to JSONL."""
    recorder = JsonlTrajectoryRecorder(args.trace) if args.trace else None
    conversation = Path(args.conversation) if args.conversation else None
    try:
        return await run_agent_task(
            Path(args.cwd),
            settings,
            spec,
            recorder=recorder,
            conversation_path=conversation,
        )
    finally:
        if recorder is not None:
            recorder.close()


async def _run(args: argparse.Namespace) -> int:
    settings = load_config(args.config)
    configure_logging(Path(args.cwd), settings, args.log_level)
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
