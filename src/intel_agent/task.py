"""Task lifecycle, budget tracking, stage state machine (port of task.ts)."""

from __future__ import annotations

import json
from pathlib import Path

from .models import (
    ChallengeRound,
    CoverageHistory,
    CoverageSnapshot,
    IntelError,
    IntelTask,
    SufficiencyCriteria,
    TaskOutputBinding,
    TaskStage,
    new_id,
    utc_now,
)
from .storage import intel_path, read_json, sha256, workspace_path, write_json_atomic

ACTIVE_TASK_FILE = "active-task.json"
STAGE_ORDER: list[TaskStage] = ["collect", "assess", "challenge", "done"]
FETCH_ATTEMPT_LIMIT = 6
SEARCH_ATTEMPT_LIMIT = 6


def create_task(cwd: Path, topic: str, questions: list[str], criteria: SufficiencyCriteria | dict) -> IntelTask:
    if isinstance(criteria, dict):
        criteria = SufficiencyCriteria.model_validate(criteria)
    topic = topic.strip()
    question_texts = list(dict.fromkeys(q.strip() for q in questions if q.strip()))
    if not topic:
        raise IntelError("INVALID_INPUT", "主题不能为空")
    if len(question_texts) < 2 or len(question_texts) > 6:
        raise IntelError("INVALID_INPUT", "关键问题数量必须为 2–6 个")
    if (
        criteria.min_independent_sources < 1
        or criteria.min_high_quality_sources < 0
        or criteria.recency_days < 1
    ):
        raise IntelError("INVALID_INPUT", "充分性标准必须是有效正整数")
    now = utc_now()
    task = IntelTask(
        id=new_id("task"),
        topic=topic,
        stage="collect",
        questions=[{"id": new_id("q"), "text": text} for text in question_texts],
        criteria=criteria,
        created_at=now,
        updated_at=now,
    )
    save_task(cwd, task)
    write_json_atomic(cwd, ACTIVE_TASK_FILE, {"task_id": task.id})
    return task


def load_task(cwd: Path, task_id: str | None = None) -> IntelTask:
    if task_id is None:
        task_id = read_json(cwd, ACTIVE_TASK_FILE)["task_id"]
    return IntelTask.model_validate(read_json(cwd, f"tasks/{task_id}.json"))


def save_task(cwd: Path, task: IntelTask) -> None:
    write_json_atomic(cwd, f"tasks/{task.id}.json", task.model_dump())


def record_fetch_attempt(cwd: Path, task_id: str | None = None) -> dict:
    task = load_task(cwd, task_id)
    if task.collection.fetch_attempts_since_evidence >= FETCH_ATTEMPT_LIMIT:
        if not task.collection.stop_reason:
            task = task.model_copy(update={"collection": task.collection.model_copy(update={"stop_reason": "fetch_without_evidence"}), "updated_at": utc_now()})
            save_task(cwd, task)
        raise IntelError(
            "COLLECTION_BUDGET_EXHAUSTED",
            f"连续抓取未新增证据已达 {FETCH_ATTEMPT_LIMIT} 次；请先保存现有文档中的有效证据并运行审核/覆盖评估，或接受缺口停止检索。",
        )
    task = task.model_copy(
        update={
            "collection": task.collection.model_copy(update={"fetch_attempts_since_evidence": task.collection.fetch_attempts_since_evidence + 1}),
            "updated_at": utc_now(),
        }
    )
    save_task(cwd, task)
    return task.collection.model_dump()


def record_search_attempt(cwd: Path, task_id: str | None = None) -> dict:
    task = load_task(cwd, task_id)
    if task.collection.search_attempts >= SEARCH_ATTEMPT_LIMIT:
        if not task.collection.search_stop_reason:
            task = task.model_copy(
                update={"collection": task.collection.model_copy(update={"search_stop_reason": "search_budget_exhausted"}), "updated_at": utc_now()}
            )
            save_task(cwd, task)
        raise IntelError(
            "SEARCH_BUDGET_EXHAUSTED",
            f"搜索预算已用完（{SEARCH_ATTEMPT_LIMIT} 次）；请使用已有候选来源，或接受并披露检索缺口。",
        )
    task = task.model_copy(
        update={
            "collection": task.collection.model_copy(update={"search_attempts": task.collection.search_attempts + 1}),
            "updated_at": utc_now(),
        }
    )
    save_task(cwd, task)
    return task.collection.model_dump()


def record_evidence_progress(cwd: Path, task_id: str, evidence_count: int) -> dict:
    task = load_task(cwd, task_id)
    if evidence_count < task.collection.evidence_count:
        raise IntelError("INVALID_INPUT", "证据进展计数无效")
    if evidence_count == task.collection.evidence_count:
        return task.collection.model_dump()
    task = task.model_copy(
        update={
            "collection": task.collection.model_copy(
                update={"fetch_attempts_since_evidence": 0, "evidence_count": evidence_count, "stop_reason": None}
            ),
            "updated_at": utc_now(),
        }
    )
    save_task(cwd, task)
    return task.collection.model_dump()


def bind_task_output(cwd: Path, task_id: str, kind: str, path: str, coverage: CoverageSnapshot) -> dict:
    task = load_task(cwd, task_id)
    if coverage.task_id != task.id:
        raise IntelError("INVALID_INPUT", "产物覆盖快照不属于任务")
    full_path = workspace_path(cwd, path)
    if not full_path.exists():
        raise IntelError("NOT_FOUND", f"产物文件不存在: {path}")
    binding = TaskOutputBinding(
        coverage_id=coverage.id,
        coverage_fingerprint=coverage.fingerprint,
        path=path,
        content_sha256=sha256(full_path.read_bytes()),
        created_at=utc_now(),
    )
    task = task.model_copy(
        update={"outputs": task.outputs.model_copy(update={kind: binding}), "updated_at": utc_now()}
    )
    save_task(cwd, task)
    return task.outputs.model_dump()


def _verify_current_outputs(cwd: Path, task: IntelTask) -> None:
    history = CoverageHistory.model_validate(read_json(cwd, f"coverage/{task.id}.json"))
    coverage = history.snapshots[-1] if history.snapshots else None
    if coverage is None:
        raise IntelError("INVALID_STAGE_TRANSITION", "缺少最新覆盖快照")
    for kind in ("package", "assessment"):
        output = task.outputs.model_dump()[kind]
        if (
            output is None
            or output["coverage_id"] != coverage.id
            or output["coverage_fingerprint"] != coverage.fingerprint
        ):
            raise IntelError("INVALID_STAGE_TRANSITION", f"{kind} 未绑定最新覆盖快照")
        full_path = workspace_path(cwd, output["path"])
        if not full_path.exists() or sha256(full_path.read_bytes()) != output["content_sha256"]:
            raise IntelError("INVALID_STAGE_TRANSITION", f"{kind} 产物缺失或已被修改")


def set_task_stage(cwd: Path, task_id: str, stage: TaskStage) -> IntelTask:
    task = load_task(cwd, task_id)
    current = STAGE_ORDER.index(task.stage)
    if STAGE_ORDER.index(stage) != current + 1:
        raise IntelError("INVALID_STAGE_TRANSITION", f"非法阶段转换: {task.stage} → {stage}")
    if stage == "assess":
        coverage_path = f"coverage/{task.id}.json"
        if not intel_path(cwd, coverage_path).exists():
            raise IntelError("INVALID_STAGE_TRANSITION", "缺少覆盖评估，不能进入研判阶段")
        history = CoverageHistory.model_validate(read_json(cwd, coverage_path))
        latest = history.snapshots[-1] if history.snapshots else None
        if latest is None or latest.stop_reason is None:
            raise IntelError("INVALID_STAGE_TRANSITION", "最新覆盖评估尚未达到停止条件，请继续补证或评估")
    if stage == "done":
        store = read_json(cwd, "challenges.json") if intel_path(cwd, "challenges.json").exists() else {"items": []}
        rounds = [ChallengeRound.model_validate(item) for item in store["items"]]
        latest = next((r for r in rounds if r.task_id == task.id and r.round == task.challenge_round), None)
        if latest is None or latest.status != "confirmed" or not latest.converged:
            raise IntelError("INVALID_STAGE_TRANSITION", "红队复审尚未确认收敛")
        _verify_current_outputs(cwd, task)
    updated = task.model_copy(update={"stage": stage, "updated_at": utc_now()})
    save_task(cwd, updated)
    return updated


def summarize_task(cwd: Path, task_id: str | None = None) -> dict:
    task = load_task(cwd, task_id)
    next_action = {
        "collect": "按问题 ID 检索并抓取文档，再保存可定位引文。",
        "assess": "运行 coverage_eval；充分或停止后生成证据包和研判。",
        "challenge": "完成最多两轮红队复审。",
        "done": "任务已完成。",
    }[task.stage]
    return {"task": task.model_dump(), "next_action": next_action}
