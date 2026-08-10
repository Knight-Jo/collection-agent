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
    parser.add_argument("--trace", default=None, help="保存完整消息轨迹到 JSONL 文件")
    return parser


def _write_trace(path: str, messages) -> None:
    import json as _json

    events = []
    for msg in messages:
        part = msg.parts[0] if msg.parts else None
        kind = type(part).__name__ if part else "none"
        if kind == "ToolCallPart":
            events.append({"type": "tool_call", "tool": part.tool_name, "args": part.args})
        elif kind == "ToolReturnPart":
            events.append({"type": "tool_result", "tool": part.tool_name, "tool_call_id": part.tool_call_id})
        elif kind == "ModelRequestPart":
            events.append({"type": "model_request", "kind": type(part).__name__})
    # 补充原始消息序列，便于深挖
    raw = []
    for msg in messages:
        try:
            raw.append(_json.loads(msg.model_dump_json()))
        except Exception:
            raw.append(str(msg))
    (Path(path)).write_text(_json.dumps({"events": events, "messages": raw}, ensure_ascii=False, indent=2), encoding="utf-8")


async def _run(args: argparse.Namespace) -> int:
    settings = load_config(args.config)
    if not settings.model_api_key():
        print("错误: 缺少模型 API key，请设置环境变量 " + settings.model.api_key_env, file=sys.stderr)
        return 1
    agent = build_agent(settings)
    deps = agent.init_deps(Path(args.cwd), settings)
    questions = "；".join(args.questions)
    recency_required = "（强制）" if args.require_recency else "（非强制，仅统计缺口不阻断）"
    prompt = (
        f"请围绕主题「{args.topic}」执行公开来源情报收集与研判。\n"
        f"【关键问题·必须原样使用】调用 intel_plan 时必须原样使用下列问题，不得替换、增删或改写：\n"
        f"{questions}\n"
        f"【充分性标准·必须照此设置】min_independent_sources={args.min_sources}，"
        f"min_high_quality_sources={args.min_quality}，recency_days={args.recency}，"
        f"require_recency={str(args.require_recency).lower()}（{recency_required}）。\n"
        f"【检索纪律】先按问题逐一 web_search（每问题至少一次），优先官方/政府/主流新闻/学术来源；"
        f"每问题定向抓取 2-3 篇不同来源组的文档；同一问题至少 2 个独立来源组才可能达到 covered。\n"
        f"【事实纪律】fact_save 只登记单一、原子、可独立核验的命题；引文必须逐字覆盖命题的"
        f"全部重要组成（主体/动作/范围/时间/数量）；evidence_audit 返回 partial 时用 fact_supersede "
        f"拆分为更窄的事实，或保存覆盖完整组成的引文。\n"
        f"【挑战纪律】intel_challenge_confirm 中 addressed 优先（引用本轮新增且已 full 审核的证据）；"
        f"确需 dismissed 时必须给出具体、可审查的理由（说明为何该缺口可接受）。\n"
        "按工作流推进：intel_plan → 逐问题检索抓取 → 事实与证据 → evidence_audit → coverage_eval"
        "（充分或 no_progress 停止）→ intel_status(assess) → generate_package + intel_assess → "
        "intel_status(challenge) → intel_challenge_start/confirm（最多 2 轮）→ 收敛后重新出包与研判 → "
        "intel_status(done)，并向用户报告结论、置信度、矛盾、缺口和产物路径。"
    )
    from pydantic_ai.usage import UsageLimits

    result = await agent.run(
        prompt,
        deps=deps,
        usage_limits=UsageLimits(request_limit=settings.budgets.request_limit),
    )
    if args.trace:
        _write_trace(args.trace, result.all_messages())
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
