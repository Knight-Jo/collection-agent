"""Fact CRUD with supersession and cycle detection (port of fact.ts)."""

from __future__ import annotations

from pathlib import Path

from .models import Fact, IntelError, normalized_statement
from .storage import intel_path, list_json, read_json, sha256, write_json_atomic
from .task import load_task


def _fact_id(task_id: str, question_id: str, statement: str) -> str:
    return f"fact-{sha256(f'{task_id}\n{question_id}\n{statement}')[:16]}"


def verify_fact(cwd: Path, fact: Fact, ancestors: set[str] | None = None) -> Fact:
    ancestors = ancestors or set()
    if not fact.id or not fact.task_id or not fact.question_id or not fact.statement:
        raise IntelError("STORAGE_CORRUPT", "事实记录不匹配")
    if fact.status not in ("active", "superseded"):
        raise IntelError("STORAGE_CORRUPT", "事实记录不匹配")
    task = load_task(cwd, fact.task_id)
    statement = normalized_statement(fact.statement)
    if (
        not statement
        or not any(q.id == fact.question_id for q in task.questions)
        or fact.statement != statement
        or fact.id != _fact_id(task.id, fact.question_id, statement)
        or (fact.status == "active" and (fact.superseded_by or fact.supersession_reason))
        or (fact.status == "superseded" and (not fact.superseded_by or not fact.supersession_reason.strip()))
        or len(set(fact.superseded_by)) != len(fact.superseded_by)
        or fact.id in fact.superseded_by
    ):
        raise IntelError("STORAGE_CORRUPT", f"事实记录不匹配: {fact.id}")
    if fact.status == "superseded":
        if fact.id in ancestors:
            raise IntelError("STORAGE_CORRUPT", f"事实替换形成循环: {fact.id}")
        next_ancestors = ancestors | {fact.id}
        for replacement_id in fact.superseded_by:
            try:
                replacement = verify_fact(cwd, Fact.model_validate(read_json(cwd, f"facts/{replacement_id}.json")), next_ancestors)
            except IntelError:
                raise IntelError("STORAGE_CORRUPT", f"事实替换记录不匹配: {fact.id}")
            if (
                replacement.id != replacement_id
                or replacement.task_id != fact.task_id
                or replacement.question_id != fact.question_id
            ):
                raise IntelError("STORAGE_CORRUPT", f"事实替换记录不匹配: {fact.id}")
    return fact


def load_fact(cwd: Path, fact_id: str) -> Fact:
    fact = verify_fact(cwd, Fact.model_validate(read_json(cwd, f"facts/{fact_id}.json")))
    if fact.id != fact_id:
        raise IntelError("STORAGE_CORRUPT", f"事实文件名与记录 ID 不匹配: {fact_id}")
    return fact


def list_facts_for_task(cwd: Path, task_id: str) -> list[Fact]:
    return [verify_fact(cwd, Fact.model_validate(item)) for item in list_json(cwd, "facts") if item.get("task_id") == task_id]


def list_facts_for_question(cwd: Path, task_id: str, question_id: str) -> list[Fact]:
    return [f for f in list_facts_for_task(cwd, task_id) if f.question_id == question_id]


def list_active_facts_for_task(cwd: Path, task_id: str) -> list[Fact]:
    return [f for f in list_facts_for_task(cwd, task_id) if f.status == "active"]


def list_active_facts_for_question(cwd: Path, task_id: str, question_id: str) -> list[Fact]:
    return [f for f in list_active_facts_for_task(cwd, task_id) if f.question_id == question_id]


def save_fact(cwd: Path, task_id: str, question_id: str, statement: str) -> Fact:
    task = load_task(cwd, task_id)
    statement = normalized_statement(statement)
    if not statement:
        raise IntelError("INVALID_INPUT", "事实陈述不能为空")
    if not any(q.id == question_id for q in task.questions):
        raise IntelError("INVALID_INPUT", f"问题不属于任务: {question_id}")
    id_ = _fact_id(task.id, question_id, statement)
    if intel_path(cwd, f"facts/{id_}.json").exists():
        return load_fact(cwd, id_)
    from .models import utc_now

    fact = Fact(
        id=id_,
        task_id=task.id,
        question_id=question_id,
        statement=statement,
        status="active",
        superseded_by=[],
        supersession_reason="",
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    write_json_atomic(cwd, f"facts/{id_}.json", fact.model_dump())
    return fact


def supersede_fact(cwd: Path, fact_id: str, replacement_fact_ids: list[str], reason: str) -> Fact:
    fact = load_fact(cwd, fact_id)
    reason = reason.strip()
    if not reason:
        raise IntelError("INVALID_INPUT", "替换事实必须提供原因")
    if fact.status != "active":
        raise IntelError("INVALID_INPUT", "事实已被替换")
    if not replacement_fact_ids:
        raise IntelError("INVALID_INPUT", "至少需要一个 replacement fact")
    replacement_ids = list(dict.fromkeys(replacement_fact_ids))
    if len(replacement_ids) != len(replacement_fact_ids) or fact.id in replacement_ids:
        raise IntelError("INVALID_INPUT", "replacement facts 必须互异且不能包含原事实")
    replacements = [load_fact(cwd, rid) for rid in replacement_ids]
    if any(
        r.status != "active" or r.task_id != fact.task_id or r.question_id != fact.question_id
        for r in replacements
    ):
        raise IntelError("INVALID_INPUT", "replacement facts 必须是同任务、同问题下的活跃事实")
    from .models import utc_now

    updated = fact.model_copy(
        update={"status": "superseded", "superseded_by": replacement_ids, "supersession_reason": reason, "updated_at": utc_now()}
    )
    write_json_atomic(cwd, f"facts/{fact.id}.json", updated.model_dump())
    return load_fact(cwd, fact.id)
