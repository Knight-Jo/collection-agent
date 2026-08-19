"""分析一次实验：从 trace/state/manifest 生成结构化摘要。

用法: python scripts/analyze_run.py experiments/runs/001-baseline
输出: 终端摘要 + <run>/ANALYSIS.md（每次覆盖）
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path


def _load_trace(run_dir: Path) -> dict:
    path = run_dir / "trace.jsonl"
    if not path.exists():
        return {"events": [], "messages": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _load_task(run_dir: Path):
    tasks_dir = run_dir / "state" / "tasks"
    if tasks_dir.exists():
        files = list(tasks_dir.glob("*.json"))
        if files:
            return json.loads(files[0].read_text(encoding="utf-8"))
    return None


def _load_coverage(run_dir: Path):
    cov_dir = run_dir / "state" / "coverage"
    if cov_dir.exists():
        files = list(cov_dir.glob("*.json"))
        if files:
            return json.loads(files[0].read_text(encoding="utf-8"))
    return None


def _load_conflicts(run_dir: Path):
    path = run_dir / "state" / "conflicts.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def _load_challenges(run_dir: Path):
    path = run_dir / "state" / "challenges.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def analyze(run_dir: Path) -> str:
    trace = _load_trace(run_dir)
    events = trace.get("events", [])
    task = _load_task(run_dir)
    coverage = _load_coverage(run_dir)
    conflicts = _load_conflicts(run_dir)
    challenges = _load_challenges(run_dir)

    lines: list[str] = [f"# 实验分析: {run_dir.name}", ""]

    manifest_path = run_dir / "manifest.json"
    if manifest_path.exists():
        m = json.loads(manifest_path.read_text(encoding="utf-8"))
        lines.append(f"- 主题: {m.get('topic')}")
        lines.append(f"- 问题: {'; '.join(m.get('questions', []))}")
        lines.append(
            f"- 耗时: {m.get('elapsed_seconds')}s  exit={m.get('exit_code')}"
        )
        lines.append(f"- git: {m.get('git_head')}")
        lines.append("")

    # 工具调用序列
    calls = [e for e in events if e["type"] == "tool_call"]
    lines.append(f"## 工具调用轨迹（共 {len(calls)} 次）")
    lines.append("")
    lines.append("| # | 工具 | 参数摘要 |")
    lines.append("|---|------|----------|")
    for i, call in enumerate(calls, 1):
        args = call.get("args", "")
        try:
            parsed = json.loads(args) if isinstance(args, str) else args
        except json.JSONDecodeError:
            parsed = {}
        summary = _summarize_args(call["tool"], parsed)
        lines.append(f"| {i} | {call['tool']} | {summary} |")
    lines.append("")

    counts = Counter(c["tool"] for c in calls)
    lines.append("### 工具调用分布")
    for tool, count in counts.most_common():
        lines.append(f"- {tool}: {count}")
    lines.append("")

    # 转化漏斗（015）：搜索 → 归档 → 阅读 → 证据 → 独立事实
    funnel = _evidence_funnel(run_dir, calls)
    if funnel:
        lines.append("## 转化漏斗（搜索→归档→阅读→证据→事实）")
        lines.append(
            f"- 搜索次数: {funnel['searches']}（矩阵 {funnel['matrix_queries']}）"
        )
        lines.append(f"- 归档文档: {funnel['archived']}")
        lines.append(
            f"- 被阅读文档: {funnel['read']}（利用率 {funnel['read_rate']:.1%}）"
        )
        lines.append(
            f"- 被证据引用文档: {funnel['cited']}（利用率 {funnel['cite_rate']:.1%}）"
        )
        lines.append(f"- 活跃事实: {funnel['active_facts']}")
        lines.append(f"- 各深度证据产出率: {funnel['depth_yield']}")
        lines.append("")

    # 重复调用检测
    repeats = _find_repeats(calls)
    if repeats:
        lines.append("### 重复/可疑调用")
        for r in repeats:
            lines.append(f"- {r}")
        lines.append("")

    # 错误与失败
    log_path = run_dir / "run.log"
    if log_path.exists():
        log_text = log_path.read_text(encoding="utf-8")
        err_codes = re.findall(r"\[([A-Z_]+)\]", log_text)
        code_counts = Counter(c for c in err_codes if c not in ("usage",))
        if code_counts:
            lines.append("### 错误码出现（run.log）")
            for code, n in code_counts.most_common():
                lines.append(f"- {code}: {n}")
            lines.append("")

    # 任务状态
    if task:
        lines.append("## 任务最终状态")
        lines.append(
            f"- stage: {task.get('stage')}  challenge_round: {task.get('challenge_round')}"
        )
        lines.append(
            f"- collection: {json.dumps(task.get('collection'), ensure_ascii=False)}"
        )
        outputs = task.get("outputs", {})
        lines.append(
            f"- outputs: package={outputs.get('package') is not None}, assessment={outputs.get('assessment') is not None}"
        )
        lines.append("")

    # 覆盖
    if coverage:
        snapshots = coverage.get("snapshots", [])
        if snapshots:
            last = snapshots[-1]
            lines.append("## 最新覆盖快照")
            lines.append(
                f"- level: {last.get('level')}  gap_score: {last.get('gap_score')}  stop_reason: {last.get('stop_reason')}"
            )
            lines.append(
                f"- no_progress_rounds: {last.get('no_progress_rounds')}"
            )
            for q in last.get("per_question", []):
                lines.append(
                    f"- Q[{q.get('status')}] {q.get('question', '')[:40]}: facts={q.get('fact_count')} covered={q.get('covered_fact_count')}"
                )
                for f in q.get("facts", []):
                    notes = "; ".join(f.get("notes", []))
                    lines.append(
                        f"    - F[{f.get('status')}] gap={f.get('gap_score')} srcs={f.get('independent_sources')} hq={f.get('high_quality_sources')} recent={f.get('recent_count')} uncf={f.get('unresolved_conflicts')} {notes}"
                    )
            lines.append("")

    # 冲突与挑战
    if conflicts and conflicts.get("items"):
        lines.append(f"## 证据冲突（{len(conflicts['items'])} 条）")
        for c in conflicts["items"]:
            lines.append(
                f"- {c['id']}: {c['resolution']} note={c.get('note', '')[:60]}"
            )
        lines.append("")
    if challenges and challenges.get("items"):
        for ch in challenges["items"]:
            lines.append(
                f"## 挑战轮次 {ch['round']}: {ch['status']} converged={ch['converged']}"
            )
            for p in ch.get("points", []):
                lines.append(
                    f"- [{p['status']}] {p['category']}: {p['challenge'][:60]}"
                )
        lines.append("")

    # 事实统计
    facts_dir = run_dir / "state" / "facts"
    if facts_dir.exists():
        facts = [
            json.loads(f.read_text(encoding="utf-8"))
            for f in facts_dir.glob("*.json")
        ]
        active = [f for f in facts if f["status"] == "active"]
        superseded = [f for f in facts if f["status"] == "superseded"]
        lines.append(
            f"## 事实统计: 总 {len(facts)}（active {len(active)} / superseded {len(superseded)}）"
        )
        for f in active:
            lines.append(f"- {f['statement'][:70]}")
        lines.append("")

    # 确定性查询矩阵（014）
    matrix_path = run_dir / "state" / "search_matrix.json"
    if matrix_path.exists():
        matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
        trace = matrix.get("trace", [])
        by_slot: dict[str, int] = {}
        by_phase: dict[str, int] = {}
        for entry in trace:
            by_slot[entry.get("slot", "?")] = (
                by_slot.get(entry.get("slot", "?"), 0) + 1
            )
            by_phase[entry.get("phase", "?")] = (
                by_phase.get(entry.get("phase", "?"), 0) + 1
            )
        lines.append("## 查询矩阵（系统确定性执行）")
        lines.append(f"- 已执行 {len(trace)} 条；phase 分布: {by_phase}")
        lines.append(f"- slot 分布: {by_slot}")
        new_domains = sum(
            1
            for entry in trace
            for item in entry.get("results", [])
            if item.get("new_domain")
        )
        lines.append(f"- 新域候选: {new_domains}")
        lines.append("")
    return "\n".join(lines)


def _evidence_funnel(run_dir: Path, calls: list[dict]) -> dict | None:
    """搜索 → 归档 → 阅读 → 证据 → 独立事实 的转化漏斗（run 015）。"""
    try:
        state_dir = run_dir / "state"
        documents = list((state_dir / "documents").glob("*.json"))
        evidence_files = list((state_dir / "evidence").glob("*.json"))
        facts = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in (state_dir / "facts").glob("*.json")
        ]
    except OSError:
        return None
    searches = sum(1 for c in calls if c["tool"] == "web_search")
    matrix_queries = 0
    matrix_path = state_dir / "search_matrix.json"
    if matrix_path.exists():
        matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
        matrix_queries = len(matrix.get("trace", []))
    read_ids: set[str] = set()
    for call in calls:
        if call["tool"] != "document_read":
            continue
        try:
            args = (
                json.loads(call["args"])
                if isinstance(call.get("args"), str)
                else call.get("args", {})
            )
        except json.JSONDecodeError:
            continue
        if args.get("document_id"):
            read_ids.add(args["document_id"])
    cited_ids: set[str] = set()
    for path in evidence_files:
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("document_id"):
            cited_ids.add(record["document_id"])
    active_facts = sum(1 for fact in facts if fact.get("status") == "active")
    depth_yield: dict[int, str] = {}
    for crawl_path in (state_dir / "crawls").glob("*.json"):
        crawl = json.loads(crawl_path.read_text(encoding="utf-8"))
        by_depth: dict[int, list[str]] = {}
        for entry in crawl.get("entries", []):
            by_depth.setdefault(entry.get("depth", 0), []).append(
                entry.get("document_id")
            )
        for depth, ids in sorted(by_depth.items()):
            doc_ids = [item for item in ids if item]
            cited = sum(1 for item in doc_ids if item in cited_ids)
            yield_rate = cited / len(doc_ids) if doc_ids else 0.0
            depth_yield[depth] = (
                f"depth={depth}: {cited}/{len(doc_ids)} ({yield_rate:.0%})"
            )
    archived = len(documents)
    return {
        "searches": searches,
        "matrix_queries": matrix_queries,
        "archived": archived,
        "read": len(read_ids),
        "read_rate": len(read_ids) / max(1, archived),
        "cited": len(cited_ids),
        "cite_rate": len(cited_ids) / max(1, archived),
        "active_facts": active_facts,
        "depth_yield": "; ".join(depth_yield.values()) or "不可计算",
    }


def _summarize_args(tool: str, args: dict) -> str:
    if tool == "web_search":
        return f"q={args.get('query', '')[:40]} n={args.get('max_results', 5)}"
    if tool == "web_fetch":
        return f"url={args.get('url', '')[:60]}"
    if tool == "intel_plan":
        return f"topic={args.get('topic', '')[:20]} q={len(args.get('questions', []))}"
    if tool in (
        "intel_status",
        "coverage_eval",
        "generate_package",
        "evidence_audit",
        "intel_assess",
    ):
        return f"task={args.get('task_id', '')[:16]}"
    if tool == "fact_save":
        return f"q={args.get('question_id', '')[:16]} stmt={args.get('statement', '')[:40]}"
    if tool == "evidence_save":
        return f"doc={args.get('document_id', '')[:16]} rel={args.get('relation')} quote={args.get('quote', '')[:30]}"
    if tool == "intel_challenge_start":
        return (
            f"round={args.get('round')} points={len(args.get('points', []))}"
        )
    if tool == "intel_challenge_confirm":
        return f"round={args.get('round')} resolutions={len(args.get('resolutions', []))}"
    return json.dumps(args, ensure_ascii=False)[:80]


def _find_repeats(calls: list[dict]) -> list[str]:
    out = []
    seq: list[tuple[str, str]] = []
    for c in calls:
        seq.append((c["tool"], c.get("args", "")))
    for i in range(len(seq) - 1):
        if seq[i] == seq[i + 1]:
            tool, args = seq[i]
            out.append(
                f"连续重复 {tool}: {_summarize_args(tool, json.loads(args) if isinstance(args, str) else args)}"
            )
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", help="experiments/runs/xxx-name")
    parser.add_argument(
        "--write", action="store_true", help="同时写入 ANALYSIS.md"
    )
    args = parser.parse_args()
    run_dir = Path(args.run_dir)
    if not run_dir.is_dir():
        print(f"找不到运行目录: {run_dir}", file=sys.stderr)
        return 1
    report = analyze(run_dir)
    print(report)
    if args.write:
        (run_dir / "ANALYSIS.md").write_text(report, encoding="utf-8")
        print(f"\n已写入 {run_dir / 'ANALYSIS.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
