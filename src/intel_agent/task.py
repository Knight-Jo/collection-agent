"""Task lifecycle, budget tracking, stage state machine (port of task.ts)."""

from __future__ import annotations

import re
from pathlib import Path

from .logging import get_logger
from .models import (
    ChallengeRound,
    CoverageHistory,
    CoverageSnapshot,
    IntelError,
    IntelQuestion,
    IntelTask,
    InvestigationItem,
    ReportDepth,
    ResearchScope,
    SufficiencyCriteria,
    TaskOutputBinding,
    TaskStage,
    new_id,
    utc_now,
)
from .state_db import connect_state_db, initialize_state_db
from .storage import (
    intel_path,
    load_crawl,
    read_json,
    read_json_object,
    sha256,
    verify_document_integrity,
    workspace_path,
    write_json_atomic,
)
from .trajectory import (
    DecisionPayload,
    emit,
    emit_state_updated,
    make_event,
    set_task_id,
)

ACTIVE_TASK_FILE = "active-task.json"
STAGE_ORDER: list[TaskStage] = ["collect", "assess", "challenge", "done"]
# Budgets mirror the original pi prototype. Search is a hard per-task cap
# (queries never get cheaper to run); fetch is a sliding window that resets on
# new evidence, so the agent is never hard-stopped mid-progress.
FETCH_ATTEMPT_LIMIT = 6
SEARCH_ATTEMPT_LIMIT = 6
# Per-phase search shares (run 063: the model's discovery searches ate the
# shared cap before matrix verify slots could run; verify must keep its own
# budget or cross-verification is structurally starved).
SEARCH_POOL_SHARES = {"discovery": 0.4, "verify": 0.4, "adversarial": 0.2}

logger = get_logger(__name__)

_YEAR_RE = re.compile(r"(?<!\d)(\d{4})(?!\d)")
_YEAR_RANGE_RE = re.compile(
    r"(?<!\d)(\d{4})年?\s*(?:至|到|[-—])\s*(\d{4})年?(?!\d)"
)
_ISO_DATE_RE = re.compile(r"(?<!\d)(\d{4})-\d{2}-\d{2}(?!\d)")


def parse_time_range(text: str) -> str:
    """Parse an explicit year constraint: YYYY or YYYY-YYYY / YYYY至YYYY.

    Returns the canonical range string or "" when no plausible year exists.
    Only deterministic formats are recognized (run 012: explicit years must
    enter the task scope instead of living in free-form question text).
    """
    if not text:
        return ""
    dates = [int(match.group(1)) for match in _ISO_DATE_RE.finditer(text)]
    if dates and all(1900 <= year <= 2100 for year in dates):
        return f"{dates[0]}-{dates[-1]}" if len(dates) > 1 else str(dates[0])
    range_match = _YEAR_RANGE_RE.search(text)
    if range_match:
        start, end = int(range_match.group(1)), int(range_match.group(2))
        if 1900 <= start <= end <= 2100:
            return f"{start}-{end}"
    for match in _YEAR_RE.finditer(text):
        year = int(match.group(1))
        if 1900 <= year <= 2100:
            return f"{year}"
    return ""


def create_task(
    cwd: Path,
    topic: str,
    questions: list[str],
    criteria: SufficiencyCriteria | dict,
    deep_crawl: bool = False,
    objective: str = "",
    scope: ResearchScope | None = None,
    report_depth: ReportDepth = "standard",
    investigation_items: dict[str, list[str]] | None = None,
) -> IntelTask:
    """Create a task with stable question IDs and persist it as the active task."""
    task = build_task(
        topic,
        questions,
        criteria,
        deep_crawl=deep_crawl,
        objective=objective,
        scope=scope,
        report_depth=report_depth,
        investigation_items=investigation_items,
    )
    save_task(cwd, task)
    write_json_atomic(cwd, ACTIVE_TASK_FILE, {"task_id": task.id})
    return task


def build_task(
    topic: str,
    questions: list[str],
    criteria: SufficiencyCriteria | dict,
    deep_crawl: bool = False,
    objective: str = "",
    scope: ResearchScope | None = None,
    report_depth: ReportDepth = "standard",
    investigation_items: dict[str, list[str]] | None = None,
) -> IntelTask:
    """Build validated task metadata without performing persistence."""
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
    resolved_scope = (scope or ResearchScope()).model_copy(deep=True)
    resolved_scope.time_range = (
        parse_time_range(resolved_scope.time_range)
        or resolved_scope.time_range.strip()
    )
    item_map = investigation_items or {}
    unknown_questions = set(item_map) - set(question_texts)
    if unknown_questions:
        raise IntelError("INVALID_INPUT", "调研项必须归属于关键问题")

    def build_question(text: str) -> IntelQuestion:
        items = list(
            dict.fromkeys(
                item.strip() for item in item_map.get(text, []) if item.strip()
            )
        )
        if len(items) > 4:
            raise IntelError(
                "INVALID_INPUT", "每个关键问题最多包含 4 个调研项"
            )
        return IntelQuestion(
            id=new_id("q"),
            text=text,
            time_range=resolved_scope.time_range or parse_time_range(text),
            investigation_items=[
                InvestigationItem(id=new_id("item"), text=item)
                for item in items
            ],
        )

    task = IntelTask(
        id=new_id("task"),
        topic=topic,
        stage="collect",
        questions=[build_question(text) for text in question_texts],
        criteria=criteria,
        objective=objective.strip(),
        scope=resolved_scope,
        report_depth=report_depth,
        deep_crawl=deep_crawl,
        created_at=now,
        updated_at=now,
    )
    return task


def load_task(cwd: Path, task_id: str | None = None) -> IntelTask:
    if task_id is None:
        task_id = read_json_object(cwd, ACTIVE_TASK_FILE)["task_id"]
    initialize_state_db(cwd)
    with connect_state_db(cwd) as connection:
        row = connection.execute(
            "SELECT task_json FROM task_state WHERE task_id = ?", (task_id,)
        ).fetchone()
    if row is not None and row["task_json"]:
        task = IntelTask.model_validate_json(row["task_json"])
    else:
        task = IntelTask.model_validate(
            read_json(cwd, f"tasks/{task_id}.json")
        )
        save_task(cwd, task)
    set_task_id(task.id)
    return task


def activate_task(cwd: Path, task_id: str) -> IntelTask:
    """Select an existing task for tools that use the active-task pointer."""
    task = load_task(cwd, task_id)
    write_json_atomic(cwd, ACTIVE_TASK_FILE, {"task_id": task.id})
    return task


def save_task(
    cwd: Path, task: IntelTask, *, run_id: str | None = None
) -> None:
    set_task_id(task.id)
    initialize_state_db(cwd)
    with connect_state_db(cwd) as connection:
        connection.execute(
            "INSERT INTO task_state(task_id, task_json, updated_at) "
            "VALUES (?, ?, ?) ON CONFLICT(task_id) DO UPDATE SET "
            "task_json = excluded.task_json, updated_at = excluded.updated_at",
            (task.id, task.model_dump_json(), task.updated_at),
        )
    if run_id is not None:
        revision_hash = sha256(task.model_dump_json())
        write_json_atomic(
            cwd, f"tasks/revisions/{revision_hash}.json", task.model_dump()
        )
        from .state_store import StateStore

        StateStore(cwd).stage_asset(
            run_id,
            "task_revision",
            task.id,
            revision_hash,
            revision_id=revision_hash,
        )


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
    *,
    run_id: str | None = None,
) -> dict:
    task = load_task(cwd, task_id)
    before = task.collection.model_dump()
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
            save_task(cwd, task, run_id=run_id)
            emit_state_updated(
                "task", task.id, before, task.collection.model_dump()
            )
        emit(
            make_event(
                "decision",
                "policy",
                DecisionPayload(
                    decision="stop_fetch",
                    reason_codes=["QUERY_BUDGET_EXHAUSTED"],
                    reason_source="rule",
                    reason_summary="连续抓取未新增证据，预算耗尽",
                    selected_action={"type": "stop"},
                    state_snapshot=before,
                ),
                layer="business",
            )
        )
        logger.warning(
            "fetch budget exhausted (%d consecutive fetches)", limit
        )
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
    save_task(cwd, task, run_id=run_id)
    emit_state_updated("task", task.id, before, task.collection.model_dump())
    return task.collection.model_dump()


def record_search_attempt(
    cwd: Path,
    task_id: str | None = None,
    limit: int = SEARCH_ATTEMPT_LIMIT,
    *,
    pool: str = "discovery",
    run_id: str | None = None,
) -> dict:
    task = load_task(cwd, task_id)
    before = task.collection.model_dump()
    by_pool = dict(task.collection.search_attempts_by_pool or {})
    used = by_pool.get(pool, 0)
    pool_limit = max(1, int(limit * SEARCH_POOL_SHARES.get(pool, 1.0)))
    if used >= pool_limit:
        all_exhausted = all(
            by_pool.get(name, 0) >= max(1, int(limit * share))
            for name, share in SEARCH_POOL_SHARES.items()
        )
        if all_exhausted and not task.collection.search_stop_reason:
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
            save_task(cwd, task, run_id=run_id)
            emit_state_updated(
                "task", task.id, before, task.collection.model_dump()
            )
        emit(
            make_event(
                "decision",
                "policy",
                DecisionPayload(
                    decision="stop_search",
                    reason_codes=["QUERY_BUDGET_EXHAUSTED"],
                    reason_source="rule",
                    reason_summary="检索预算耗尽",
                    selected_action={"type": "stop"},
                    state_snapshot=before,
                ),
                layer="business",
            )
        )
        logger.warning(
            "search budget exhausted (%s pool: %d/%d)",
            pool,
            used,
            pool_limit,
        )
        raise IntelError(
            "SEARCH_BUDGET_EXHAUSTED",
            f"{pool} 阶段搜索预算已用完（{pool_limit} 次）；"
            "请使用已有候选来源，或接受并披露检索缺口。",
        )
    by_pool[pool] = used + 1
    task = task.model_copy(
        update={
            "collection": task.collection.model_copy(
                update={
                    "search_attempts": task.collection.search_attempts + 1,
                    "search_attempts_by_pool": by_pool,
                }
            ),
            "updated_at": utc_now(),
        }
    )
    save_task(cwd, task, run_id=run_id)
    emit_state_updated("task", task.id, before, task.collection.model_dump())
    return task.collection.model_dump()


def record_evidence_progress(
    cwd: Path,
    task_id: str,
    evidence_count: int,
    *,
    run_id: str | None = None,
) -> dict:
    # Real progress resets the fetch window and clears the stop reason: the
    # fetch budget is a "attempts since last evidence" counter, not a total cap.
    task = load_task(cwd, task_id)
    if evidence_count < task.collection.evidence_count:
        raise IntelError("INVALID_INPUT", "证据进展计数无效")
    if evidence_count == task.collection.evidence_count:
        return task.collection.model_dump()
    before = task.collection.model_dump()
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
    save_task(cwd, task, run_id=run_id)
    emit_state_updated("task", task.id, before, task.collection.model_dump())
    return task.collection.model_dump()


def bind_task_output(
    cwd: Path,
    task_id: str,
    kind: str,
    path: str,
    coverage: CoverageSnapshot,
    *,
    document_hashes: dict[str, str] | None = None,
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
        document_hashes=document_hashes or {},
    )
    task = task.model_copy(
        update={
            "outputs": task.outputs.model_copy(update={kind: binding}),
            "updated_at": utc_now(),
        }
    )
    save_task(cwd, task)
    return task.outputs.model_dump()


def _verify_current_outputs(cwd: Path, task: IntelTask) -> CoverageSnapshot:
    history = CoverageHistory.model_validate(
        read_json(cwd, f"coverage/{task.id}.json")
    )
    coverage = history.snapshots[-1] if history.snapshots else None
    if coverage is None:
        raise IntelError("INVALID_STAGE_TRANSITION", "缺少最新覆盖快照")
    outputs = (
        (("report", task.outputs.report),)
        if task.outputs.report
        else (
            ("package", task.outputs.package),
            ("assessment", task.outputs.assessment),
        )
    )
    if task.outputs.report:
        from .coverage import current_coverage_fingerprint

        try:
            current_fingerprint = current_coverage_fingerprint(cwd, task.id)
        except IntelError as error:
            raise IntelError(
                "INVALID_STAGE_TRANSITION", "当前证据状态无效或已被修改"
            ) from error
        if coverage.fingerprint != current_fingerprint:
            raise IntelError(
                "INVALID_STAGE_TRANSITION", "事实、证据审核或冲突状态已变化"
            )
    for kind, output in outputs:
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
        for document_id, expected_hash in output.document_hashes.items():
            try:
                from .evidence import load_document

                document = load_document(cwd, document_id)
                verify_document_integrity(cwd, document)
            except IntelError as error:
                raise IntelError(
                    "INVALID_STAGE_TRANSITION",
                    f"{kind} 引用文档缺失或已被修改: {document_id}",
                ) from error
            if document.text_sha256 != expected_hash:
                raise IntelError(
                    "INVALID_STAGE_TRANSITION",
                    f"{kind} 引用文档版本已变化: {document_id}",
                )
    return coverage


def report_output_is_current(cwd: Path, task_id: str) -> bool:
    """Return whether a report is bound to the current verified facts."""
    task = load_task(cwd, task_id)
    if task.outputs.report is None:
        return False
    try:
        _verify_current_outputs(cwd, task)
    except IntelError:
        return False
    return True


def set_task_stage(
    cwd: Path,
    task_id: str,
    stage: TaskStage,
    *,
    run_id: str | None = None,
) -> IntelTask:
    """Advance stage by exactly one step; assess/done enforce hard preconditions."""
    task = load_task(cwd, task_id)
    current = STAGE_ORDER.index(task.stage)
    report_completion = task.stage == "assess" and stage == "done"
    if not report_completion and STAGE_ORDER.index(stage) != current + 1:
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
    latest_challenge = None
    if stage == "done" and task.outputs.report is None:
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
    coverage = _verify_current_outputs(cwd, task) if stage == "done" else None
    updates = {"stage": stage, "updated_at": utc_now()}
    if stage == "done":
        updates["completion_status"] = (
            "sufficient"
            if coverage and coverage.level == "sufficient"
            else "with_gaps"
        )
    updated = task.model_copy(update=updates)
    save_task(cwd, updated, run_id=run_id)
    logger.info("stage %s -> %s", task.stage, updated.stage)
    emit_state_updated(
        "task", updated.id, {"stage": task.stage}, {"stage": updated.stage}
    )
    return updated


def summarize_task(cwd: Path, task_id: str | None = None) -> dict:
    """Return task state plus a next-action hint (terminal guidance when stuck)."""
    task = load_task(cwd, task_id)
    next_action = {
        "collect": "按问题 ID 检索并抓取文档，再保存可定位引文。",
        "assess": "生成材料导读和正式调研报告后完成任务。",
        "challenge": "完成可选红队复审并更新正式调研报告。",
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
                    "正式调研报告，再调用 intel_status(stage=done) 以 with_gaps"
                    " 终态完成，并向用户披露结论、置信度、矛盾和缺口。"
                )
    return {"task": task.model_dump(), "next_action": next_action}
