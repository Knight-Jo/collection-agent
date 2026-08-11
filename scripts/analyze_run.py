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
    return "\n".join(lines)


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
