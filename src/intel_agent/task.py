"""Task lifecycle, budget tracking, stage state machine (port of task.ts)."""

from __future__ import annotations

from pathlib import Path

from .models import (
    ChallengeRound,
    CoverageHistory,
    CoverageSnapshot,
    IntelError,
    IntelQuestion,
    IntelTask,
    SufficiencyCriteria,
    TaskOutputBinding,
    TaskStage,
    new_id,
    utc_now,
)
from .storage import (
    intel_path,
    load_crawl,
    read_json,
    read_json_object,
    sha256,
    workspace_path,
    write_json_atomic,
)

ACTIVE_TASK_FILE = "active-task.json"
STAGE_ORDER: list[TaskStage] = ["collect", "assess", "challenge", "done"]
# Budgets mirror the original pi prototype. Search is a hard per-task cap
# (queries never get cheaper to run); fetch is a sliding window that resets on
# new evidence, so the agent is never hard-stopped mid-progress.
FETCH_ATTEMPT_LIMIT = 6
SEARCH_ATTEMPT_LIMIT = 6


def create_task(
    cwd: Path,
    topic: str,
    questions: list[str],
    criteria: SufficiencyCriteria | dict,
    deep_crawl: bool = False,
) -> IntelTask:
    """Create a task with stable question IDs and persist it as the active task."""
    if isinstance(criteria, dict):
        criteria = SufficiencyCriteria.model_validate(criteria)
    else:
        criteria = criteria.model_copy(deep=True)
    topic = topic.strip()
    question_texts = list(
        dict.fromkeys(q.strip() for q in questions if q.strip())
    )
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
        questions=[
            IntelQuestion(id=new_id("q"), text=text) for text in question_texts
        ],
        criteria=criteria,
        deep_crawl=deep_crawl,
        created_at=now,
        updated_at=now,
    )
    save_task(cwd, task)
    write_json_atomic(cwd, ACTIVE_TASK_FILE, {"task_id": task.id})
    return task


def load_task(cwd: Path, task_id: str | None = None) -> IntelTask:
    if task_id is None:
        task_id = read_json_object(cwd, ACTIVE_TASK_FILE)["task_id"]
    return IntelTask.model_validate(read_json(cwd, f"tasks/{task_id}.json"))


def save_task(cwd: Path, task: IntelTask) -> None:
    write_json_atomic(cwd, f"tasks/{task.id}.json", task.model_dump())


def require_crawl_complete(cwd: Path, task: IntelTask) -> None:
    """Reject workflow assessment while a deep-crawl frontier is executable."""
    if not task.deep_crawl:
        return
    try:
        crawl = load_crawl(cwd, task.id)
    except IntelError as error:
        if error.code != "NOT_FOUND":
            raise
        raise IntelError(
            "CRAWL_INCOMPLETE", "深度抓取尚未开始，不能评估覆盖"
        ) from error
    if any(entry.status in {"queued", "fetching"} for entry in crawl.entries):
        raise IntelError(
            "CRAWL_INCOMPLETE", "深度抓取仍有待处理 URL，不能评估覆盖"
        )


def record_fetch_attempt(
    cwd: Path,
    task_id: str | None = None,
    limit: int = FETCH_ATTEMPT_LIMIT,
) -> dict:
    task = load_task(cwd, task_id)
    if task.collection.fetch_attempts_since_evidence >= limit:
        if not task.collection.stop_reason:
            task = task.model_copy(
                update={
                    "collection": task.collection.model_copy(
                        update={"stop_reason": "fetch_without_evidence"}
                    ),
                    "updated_at": utc_now(),
                }
            )
            save_task(cwd, task)
        raise IntelError(
            "COLLECTION_BUDGET_EXHAUSTED",
            f"连续抓取未新增证据已达 {limit} 次；请先保存现有文档中的有效证据并运行审核/覆盖评估，或接受缺口停止检索。",
        )
    task = task.model_copy(
        update={
            "collection": task.collection.model_copy(
                update={
                    "fetch_attempts_since_evidence": task.collection.fetch_attempts_since_evidence
                    + 1
                }
            ),
            "updated_at": utc_now(),
        }
    )
    save_task(cwd, task)
    return task.collection.model_dump()


def record_search_attempt(
    cwd: Path,
    task_id: str | None = None,
    limit: int = SEARCH_ATTEMPT_LIMIT,
) -> dict:
    task = load_task(cwd, task_id)
    if task.collection.search_attempts >= limit:
        if not task.collection.search_stop_reason:
            task = task.model_copy(
                update={
                    "collection": task.collection.model_copy(
                        update={
                            "search_stop_reason": "search_budget_exhausted"
                        }
                    ),
                    "updated_at": utc_now(),
                }
            )
            save_task(cwd, task)
        raise IntelError(
            "SEARCH_BUDGET_EXHAUSTED",
            f"搜索预算已用完（{limit} 次）；请使用已有候选来源，或接受并披露检索缺口。",
        )
    task = task.model_copy(
        update={
            "collection": task.collection.model_copy(
                update={"search_attempts": task.collection.search_attempts + 1}
            ),
            "updated_at": utc_now(),
        }
    )
    save_task(cwd, task)
    return task.collection.model_dump()


def record_evidence_progress(
    cwd: Path, task_id: str, evidence_count: int
) -> dict:
    # Real progress resets the fetch window and clears the stop reason: the
    # fetch budget is a "attempts since last evidence" counter, not a total cap.
    task = load_task(cwd, task_id)
    if evidence_count < task.collection.evidence_count:
        raise IntelError("INVALID_INPUT", "证据进展计数无效")
    if evidence_count == task.collection.evidence_count:
        return task.collection.model_dump()
    task = task.model_copy(
        update={
            "collection": task.collection.model_copy(
                update={
                    "fetch_attempts_since_evidence": 0,
                    "evidence_count": evidence_count,
                    "stop_reason": None,
                }
            ),
            "updated_at": utc_now(),
        }
    )
    save_task(cwd, task)
    return task.collection.model_dump()


def bind_task_output(
    cwd: Path, task_id: str, kind: str, path: str, coverage: CoverageSnapshot
) -> dict:
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
        update={
            "outputs": task.outputs.model_copy(update={kind: binding}),
            "updated_at": utc_now(),
        }
    )
    save_task(cwd, task)
    return task.outputs.model_dump()


def _verify_current_outputs(cwd: Path, task: IntelTask) -> None:
    history = CoverageHistory.model_validate(
        read_json(cwd, f"coverage/{task.id}.json")
    )
    coverage = history.snapshots[-1] if history.snapshots else None
    if coverage is None:
        raise IntelError("INVALID_STAGE_TRANSITION", "缺少最新覆盖快照")
    for kind, output in (
        ("package", task.outputs.package),
        ("assessment", task.outputs.assessment),
    ):
        if (
            output is None
            or output.coverage_id != coverage.id
            or output.coverage_fingerprint != coverage.fingerprint
        ):
            raise IntelError(
                "INVALID_STAGE_TRANSITION", f"{kind} 未绑定最新覆盖快照"
            )
        full_path = workspace_path(cwd, output.path)
        if (
            not full_path.exists()
            or sha256(full_path.read_bytes()) != output.content_sha256
        ):
            raise IntelError(
                "INVALID_STAGE_TRANSITION", f"{kind} 产物缺失或已被修改"
            )


def set_task_stage(cwd: Path, task_id: str, stage: TaskStage) -> IntelTask:
    """Advance stage by exactly one step; assess/done enforce hard preconditions."""
    task = load_task(cwd, task_id)
    current = STAGE_ORDER.index(task.stage)
    if STAGE_ORDER.index(stage) != current + 1:
        raise IntelError(
            "INVALID_STAGE_TRANSITION", f"非法阶段转换: {task.stage} → {stage}"
        )
    if stage == "assess":
        require_crawl_complete(cwd, task)
        coverage_path = f"coverage/{task.id}.json"
        if not intel_path(cwd, coverage_path).exists():
            raise IntelError(
                "INVALID_STAGE_TRANSITION", "缺少覆盖评估，不能进入研判阶段"
            )
        history = CoverageHistory.model_validate(read_json(cwd, coverage_path))
        latest = history.snapshots[-1] if history.snapshots else None
        if latest is None or latest.stop_reason is None:
            raise IntelError(
                "INVALID_STAGE_TRANSITION",
                "最新覆盖评估尚未达到停止条件，请继续补证或评估",
            )
    if stage == "done":
        store = (
            read_json_object(cwd, "challenges.json")
            if intel_path(cwd, "challenges.json").exists()
            else {"items": []}
        )
        rounds = [
            ChallengeRound.model_validate(item) for item in store["items"]
        ]
        latest_challenge = next(
            (
                r
                for r in rounds
                if r.task_id == task.id and r.round == task.challenge_round
            ),
            None,
        )
        if latest_challenge is None or latest_challenge.status != "confirmed":
            raise IntelError("INVALID_STAGE_TRANSITION", "红队复审尚未确认")
        if not latest_challenge.converged and task.challenge_round < 2:
            raise IntelError(
                "INVALID_STAGE_TRANSITION", "红队复审尚未确认收敛"
            )
        _verify_current_outputs(cwd, task)
    updates = {"stage": stage, "updated_at": utc_now()}
    if stage == "done":
        updates["completion_status"] = (
            "sufficient"
            if latest_challenge and latest_challenge.converged
            else "with_gaps"
        )
    updated = task.model_copy(update=updates)
    save_task(cwd, updated)
    return updated


def summarize_task(cwd: Path, task_id: str | None = None) -> dict:
    """Return task state plus a next-action hint (terminal guidance when stuck)."""
    task = load_task(cwd, task_id)
    next_action = {
        "collect": "按问题 ID 检索并抓取文档，再保存可定位引文。",
        "assess": "运行 coverage_eval；充分或停止后生成证据包和研判。",
        "challenge": "完成最多两轮红队复审。",
        "done": (
            "任务已完成，但保留已披露的证据缺口。"
            if task.completion_status == "with_gaps"
            else "任务已完成。"
        ),
    }[task.stage]
    # 防死循环：两轮红队已确认但仍未收敛时给出终态指引
    if task.stage == "challenge" and task.challenge_round >= 2:
        challenges_path = intel_path(cwd, "challenges.json")
        if challenges_path.exists():
            store = read_json_object(cwd, "challenges.json")
            latest = next(
                (
                    r
                    for r in store.get("items", [])
                    if r.get("task_id") == task.id
                    and r.get("round") == task.challenge_round
                ),
                None,
            )
            if (
                latest
                and latest.get("status") == "confirmed"
                and not latest.get("converged")
            ):
                next_action = (
                    "已完成两轮红队复审且仍有缺口。请基于最新覆盖重新生成"
                    "证据包和研判，再调用 intel_status(stage=done) 以 with_gaps"
                    " 终态完成，并向用户披露结论、置信度、矛盾和缺口。"
                )
    return {"task": task.model_dump(), "next_action": next_action}
