"""Red-team challenge lifecycle (port of challenge.ts)."""

from __future__ import annotations

from pathlib import Path

from .audit import is_full_support
from .coverage import eval_coverage
from .evidence import list_evidence_for_task
from .fact import load_fact
from .models import ChallengePoint, ChallengeRound, IntelError, new_id, utc_now
from .storage import intel_path, read_json, write_json_atomic
from .task import load_task, save_task


def _load_store(cwd: Path) -> dict:
    if not intel_path(cwd, "challenges.json").exists():
        return {"items": []}
    store = read_json(cwd, "challenges.json")
    if not isinstance(store, dict) or not isinstance(store.get("items"), list):
        raise IntelError("STORAGE_CORRUPT", "challenges.json 缺少 items")
    return store


def start_challenge(cwd: Path, task_id: str, round_: int, points: list[dict]) -> ChallengeRound:
    task = load_task(cwd, task_id)
    if round_ < 1 or round_ > 2:
        raise IntelError("CHALLENGE_LIMIT", "红队复审最多两轮")
    store = _load_store(cwd)
    if any(i.get("task_id") == task.id and i.get("round") == round_ for i in store["items"]):
        raise IntelError("CHALLENGE_INVALID", f"挑战轮次已存在: {round_}")
    if round_ != task.challenge_round + 1:
        raise IntelError("CHALLENGE_INVALID", f"轮次必须连续，当前应为 {task.challenge_round + 1}")
    if round_ > 1:
        previous = next(
            (i for i in store["items"] if i.get("task_id") == task.id and i.get("round") == round_ - 1), None
        )
        if previous is None or previous.get("status") != "confirmed":
            raise IntelError("CHALLENGE_INVALID", "上一轮尚未确认")
    if not points:
        raise IntelError("CHALLENGE_INVALID", "挑战至少包含一个挑战点")
    valid_question_ids = {q.id for q in task.questions}
    challenge_points: list[ChallengePoint] = []
    for point in points:
        question_ids = list(dict.fromkeys(point.get("question_ids", [])))
        if (
            not question_ids
            or any(qid not in valid_question_ids for qid in question_ids)
            or not str(point.get("category", "")).strip()
            or not str(point.get("challenge", "")).strip()
            or not str(point.get("gap_action", "")).strip()
        ):
            raise IntelError("CHALLENGE_INVALID", "挑战点字段或问题 ID 无效")
        challenge_points.append(
            ChallengePoint(
                id=new_id(f"cp-r{round_}"),
                question_ids=question_ids,
                category=str(point["category"]).strip(),
                challenge=str(point["challenge"]).strip(),
                gap_action=str(point["gap_action"]).strip(),
                status="open",
                reason="",
                new_evidence_ids=[],
            )
        )
    round_obj = ChallengeRound(
        id=new_id("challenge"),
        task_id=task.id,
        round=round_,
        status="open",
        evidence_ids_before=[e.id for e in list_evidence_for_task(cwd, task.id)],
        points=challenge_points,
        accepted_partial_questions=[],
        converged=False,
        created_at=utc_now(),
        confirmed_at=None,
    )
    write_json_atomic(
        cwd, "challenges.json", {"items": store["items"] + [round_obj.model_dump()]}
    )
    save_task(cwd, task.model_copy(update={"challenge_round": round_, "updated_at": utc_now()}))
    return round_obj


def confirm_challenge(
    cwd: Path,
    task_id: str,
    round_: int,
    resolutions: list[dict],
    accepted_partial_questions: list[dict],
) -> ChallengeRound:
    task = load_task(cwd, task_id)
    store = _load_store(cwd)
    round_data = next(
        (i for i in store["items"] if i.get("task_id") == task.id and i.get("round") == round_ and i.get("status") == "open"),
        None,
    )
    if round_data is None:
        raise IntelError("CHALLENGE_INVALID", f"未找到开放挑战轮次: {round_}")
    round_obj = ChallengeRound.model_validate(round_data)
    for accepted in accepted_partial_questions:
        if not any(q.id == accepted.get("question_id") for q in task.questions):
            raise IntelError("CHALLENGE_INVALID", f"接受不充分问题 ID 无效: {accepted.get('question_id')}")
        if not str(accepted.get("reason", "")).strip():
            raise IntelError("CHALLENGE_INVALID", "接受不充分问题必须提供理由")
    resolutions_map = {r.get("point_id"): r for r in resolutions}
    if len(resolutions_map) != len(round_obj.points) or any(p.id not in resolutions_map for p in round_obj.points):
        raise IntelError("CHALLENGE_INVALID", "必须处理本轮全部挑战点")
    evidence_by_id = {e.id: e for e in list_evidence_for_task(cwd, task.id)}
    before = set(round_obj.evidence_ids_before)
    points: list[ChallengePoint] = []
    for point in round_obj.points:
        resolution = resolutions_map[point.id]
        reason = str(resolution.get("reason", "")).strip()
        if not reason:
            raise IntelError(
                "CHALLENGE_INVALID",
                "驳回挑战必须提供理由" if resolution.get("status") == "dismissed" else "处理挑战必须提供理由",
            )
        if resolution.get("status") == "dismissed":
            points.append(point.model_copy(update={"status": "dismissed", "reason": reason}))
            continue
        new_evidence_ids = list(dict.fromkeys(resolution.get("new_evidence_ids", [])))
        if not new_evidence_ids:
            raise IntelError("CHALLENGE_INVALID", "addressed 必须提供新增证据")
        for evidence_id in new_evidence_ids:
            if evidence_id in before:
                raise IntelError("CHALLENGE_INVALID", f"不是挑战后新增证据: {evidence_id}")
            evidence = evidence_by_id.get(evidence_id)
            if evidence is None:
                raise IntelError("CHALLENGE_INVALID", f"新增证据不存在: {evidence_id}")
            fact = load_fact(cwd, evidence.fact_id)
            if fact.status != "active":
                raise IntelError("CHALLENGE_INVALID", f"新增证据属于已替换事实: {evidence_id}")
            if evidence.relation == "supports" and not is_full_support(cwd, evidence):
                raise IntelError("CHALLENGE_INVALID", f"新增支持证据未通过完整语义审核: {evidence_id}")
            if fact.question_id not in point.question_ids:
                raise IntelError("CHALLENGE_INVALID", f"新增证据与挑战问题无关: {evidence_id}")
        points.append(
            point.model_copy(update={"status": "addressed", "reason": reason, "new_evidence_ids": new_evidence_ids})
        )
    coverage = eval_coverage(cwd, task.id)
    accepted_ids = {a.get("question_id") for a in accepted_partial_questions}
    weak_questions = [
        q for q in coverage.per_question if q.status != "covered" and q.question_id not in accepted_ids
    ]
    confirmed = round_obj.model_copy(
        update={
            "status": "confirmed",
            "points": points,
            "accepted_partial_questions": [
                {"question_id": a["question_id"], "reason": str(a["reason"]).strip()} for a in accepted_partial_questions
            ],
            "converged": len(weak_questions) == 0,
            "confirmed_at": utc_now(),
        }
    )
    write_json_atomic(
        cwd,
        "challenges.json",
        {"items": [confirmed.model_dump() if i.get("id") == round_obj.id else i for i in store["items"]]},
    )
    return confirmed
