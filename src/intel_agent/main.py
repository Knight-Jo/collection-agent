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

from .agent import build_agent
from .config import Settings, load_config


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OSINT collection agent (pydantic-ai port)")
    parser.add_argument("--topic", required=True, help="情报收集主题")
    parser.add_argument("--questions", nargs="+", required=True, help="2-6 个关键问题")
    parser.add_argument("--config", default=None, help="config.yaml 路径")
    parser.add_argument("--cwd", default=".", help="工作目录（data/intel 等相对此目录）")
    parser.add_argument("--min-sources", type=int, default=2, help="每个问题最少独立来源组")
    parser.add_argument("--min-quality", type=int, default=1, help="每个问题最少高质量来源组")
    parser.add_argument("--recency", type=int, default=90, help="时效窗口（天）")
    parser.add_argument("--require-recency", action="store_true", help="强制时效要求")
    parser.add_argument("--max-turns", type=int, default=40, help="agent 最大工具轮次")
    return parser


async def _run(args: argparse.Namespace) -> int:
    settings = load_config(args.config)
    if not settings.model_api_key():
        print("错误: 缺少模型 API key，请设置环境变量 " + settings.model.api_key_env, file=sys.stderr)
        return 1
    agent = build_agent(settings)
    deps = agent.init_deps(Path(args.cwd), settings)
    prompt = (
        f"请围绕主题「{args.topic}」执行公开来源情报收集与研判。"
        f"按工作流推进：intel_plan 规划问题（至少 {args.min_sources} 个独立来源组、"
        f"{args.min_quality} 个高质量来源组、{args.recency} 天时效{'（强制）' if args.require_recency else ''}）"
        "，逐问题检索抓取、登记事实与证据、语义审核、覆盖评估，生成证据包和研判报告，"
        "红队复审收敛后将阶段推进到 done，并向用户报告结论、置信度、矛盾、缺口和产物路径。"
    )
    result = await agent.run(prompt, deps=deps)
    print(result.output)
    usage = result.usage()
    print(f"\n[usage] requests={usage.requests} total_tokens={usage.total_tokens}")
    return 0


def main() -> int:
    args = _build_parser().parse_args()
    if not 2 <= len(args.questions) <= 6:
        print("错误: questions 数量必须为 2-6 个", file=sys.stderr)
        return 1
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
