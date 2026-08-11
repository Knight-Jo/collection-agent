"""Evidence conflict management (port of conflicts.ts)."""

from __future__ import annotations

from pathlib import Path

from .audit import is_full_support
from .evidence import list_evidence_for_fact
from .fact import load_fact
from .models import EvidenceConflict, IntelError, new_id, utc_now
from .storage import intel_path, read_json, write_json_atomic


def _load_store(cwd: Path) -> dict:
    path = intel_path(cwd, "conflicts.json")
    if not path.exists():
        return {"items": []}
    store = read_json(cwd, "conflicts.json")
    if not isinstance(store, dict) or not isinstance(store.get("items"), list):
        raise IntelError("STORAGE_CORRUPT", "conflicts.json 缺少 items")
    return store


def verify_conflict(cwd: Path, conflict: EvidenceConflict) -> EvidenceConflict:
    if (
        not conflict.id
        or not conflict.task_id
        or not conflict.fact_id
        or not isinstance(conflict.evidence_ids, list)
        or not all(isinstance(i, str) for i in conflict.evidence_ids)
        or conflict.resolution not in ("unresolved", "resolved")
    ):
        raise IntelError("STORAGE_CORRUPT", "矛盾记录不匹配")
    fact = load_fact(cwd, conflict.fact_id)
    fact_evidence = list_evidence_for_fact(cwd, fact.id)
    evidence_ids = {e.id for e in fact_evidence}
    conflict_evidence = [
        e for e in fact_evidence if e.id in conflict.evidence_ids
    ]
    if (
        conflict.task_id != fact.task_id
        or len(conflict.evidence_ids) < 2
        or any(eid not in evidence_ids for eid in conflict.evidence_ids)
        or not any(is_full_support(cwd, e) for e in conflict_evidence)
        or not any(e.relation == "contradicts" for e in conflict_evidence)
    ):
        raise IntelError("STORAGE_CORRUPT", f"矛盾记录不匹配: {conflict.id}")
    return conflict


def load_conflicts(
    cwd: Path, task_id: str | None = None
) -> list[EvidenceConflict]:
    items = [
        verify_conflict(cwd, EvidenceConflict.model_validate(item))
        for item in _load_store(cwd)["items"]
    ]
    return [i for i in items if i.task_id == task_id] if task_id else items


def save_conflict(
    cwd: Path, fact_id: str, evidence_ids: list[str]
) -> EvidenceConflict:
    fact = load_fact(cwd, fact_id)
    evidence_ids = list(dict.fromkeys(evidence_ids))
    if len(evidence_ids) < 2:
        raise IntelError("INVALID_INPUT", "矛盾必须包含至少两条证据")
    evidence_by_id = {e.id: e for e in list_evidence_for_fact(cwd, fact.id)}
    evidence = [evidence_by_id.get(eid) for eid in evidence_ids]
    if any(e is None for e in evidence):
        raise IntelError("INVALID_INPUT", "矛盾证据不存在或不属于同一事实")
    relations = {e.relation for e in evidence if e is not None}
    if "supports" not in relations or "contradicts" not in relations:
        raise IntelError(
            "INVALID_INPUT", "矛盾证据必须同时包含 supports 和 contradicts"
        )
    if not any(
        e is not None and e.relation == "supports" and is_full_support(cwd, e)
        for e in evidence
    ):
        raise IntelError("INVALID_INPUT", "矛盾的支持侧必须通过完整语义审核")
    now = utc_now()
    conflict = EvidenceConflict(
        id=new_id("cf"),
        task_id=fact.task_id,
        fact_id=fact.id,
        evidence_ids=evidence_ids,
        resolution="unresolved",
        note="",
        created_at=now,
        updated_at=now,
    )
    write_json_atomic(
        cwd,
        "conflicts.json",
        {
            "items": [c.model_dump() for c in load_conflicts(cwd)]
            + [conflict.model_dump()]
        },
    )
    return conflict


def resolve_conflict(
    cwd: Path, conflict_id: str, note: str
) -> EvidenceConflict:
    if not note.strip():
        raise IntelError("INVALID_INPUT", "消解矛盾必须提供依据")
    items = load_conflicts(cwd)
    conflict = next((i for i in items if i.id == conflict_id), None)
    if not conflict:
        raise IntelError("NOT_FOUND", f"矛盾不存在: {conflict_id}")
    updated = conflict.model_copy(
        update={
            "resolution": "resolved",
            "note": note.strip(),
            "updated_at": utc_now(),
        }
    )
    write_json_atomic(
        cwd,
        "conflicts.json",
        {
            "items": [
                updated.model_dump() if i.id == conflict.id else i.model_dump()
                for i in items
            ]
        },
    )
    return updated
