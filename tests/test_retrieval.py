from __future__ import annotations

import pytest

from intel_agent.fact import save_fact
from intel_agent.materials import register_material
from intel_agent.models import (
    AssetRevisionRef,
    CommittedResearchSnapshot,
    IntelError,
)
from intel_agent.retrieval import TaskRetriever
from intel_agent.state_store import StateStore
from intel_agent.storage import workspace_path
from tests.conftest import make_document, new_task, save_evidence


def test_retrieve_ranks_committed_evidence_before_material(cwd):
    task = new_task(
        cwd,
        ["What is the cobalt supply status?", "What are the supply risks?"],
    )
    evidence_document = make_document(
        cwd,
        "Background\nCobalt supply reached 42 units.\nConclusion",
        "https://example.com/evidence",
    )
    clue_document = make_document(
        cwd,
        "Cobalt supply may change next year.",
        "https://example.com/clue",
    )
    register_material(
        cwd,
        task.id,
        evidence_document.canonical_url,
        document_id=evidence_document.id,
    )
    register_material(
        cwd,
        task.id,
        clue_document.canonical_url,
        document_id=clue_document.id,
    )
    fact = save_fact(
        cwd,
        task.id,
        task.questions[0].id,
        "Cobalt supply reached 42 units.",
    )
    evidence = save_evidence(
        cwd,
        fact.id,
        evidence_document,
        "supports",
        "Cobalt supply reached 42 units.",
    )
    store = StateStore(cwd)
    retriever = TaskRetriever(cwd, store)

    retriever.seed_completed_task(task.id)
    passages = retriever.retrieve(task.id, "cobalt supply")

    assert passages[0].citation_kind == "verified_evidence"
    assert passages[0].evidence_id == evidence.id
    assert passages[0].line_start == 2
    assert passages[0].source_content_hash == evidence_document.text_sha256
    assert any(item.citation_kind == "material_clue" for item in passages)


def test_retrieve_excludes_uncommitted_and_cross_task_assets(cwd):
    task = new_task(cwd, ["Find launch details", "Find launch risks"])
    committed = make_document(
        cwd, "Launch baseline detail", "https://example.com/committed"
    )
    register_material(
        cwd,
        task.id,
        committed.canonical_url,
        document_id=committed.id,
    )
    store = StateStore(cwd)
    retriever = TaskRetriever(cwd, store)
    retriever.seed_completed_task(task.id)

    uncommitted = make_document(
        cwd, "Launch secret detail", "https://example.com/uncommitted"
    )
    register_material(
        cwd,
        task.id,
        uncommitted.canonical_url,
        document_id=uncommitted.id,
    )
    other_task = new_task(cwd, ["Other launch", "Other risks"])
    other = make_document(
        cwd, "Launch cross task detail", "https://other.example.com/source"
    )
    register_material(
        cwd,
        other_task.id,
        other.canonical_url,
        document_id=other.id,
    )
    store.register_task(other_task.id)
    store.seed_committed_assets(other_task.id, [("document", other.id)])

    document_ids = {
        item.document_id
        for item in retriever.retrieve(task.id, "launch detail")
    }

    assert committed.id in document_ids
    assert uncommitted.id not in document_ids
    assert other.id not in document_ids


def test_retrieve_rejects_tampered_document(cwd):
    task = new_task(cwd, ["Find launch details", "Find launch risks"])
    document = make_document(cwd, "Launch detail")
    register_material(
        cwd,
        task.id,
        document.canonical_url,
        document_id=document.id,
    )
    store = StateStore(cwd)
    retriever = TaskRetriever(cwd, store)
    retriever.seed_completed_task(task.id)
    workspace_path(cwd, document.text_path).write_text(
        "tampered launch detail", encoding="utf-8"
    )

    with pytest.raises(IntelError) as caught:
        retriever.retrieve(task.id, "launch detail")

    assert caught.value.code == "DOCUMENT_TAMPERED"


def test_retrieve_honors_fixed_snapshot_manifest(cwd):
    task = new_task(cwd, ["Find launch details", "Find launch risks"])
    first = make_document(
        cwd, "Launch baseline detail", "https://example.com/first"
    )
    second = make_document(
        cwd, "Launch second detail", "https://example.com/second"
    )
    for document in (first, second):
        register_material(
            cwd, task.id, document.canonical_url, document_id=document.id
        )
    store = StateStore(cwd)
    retriever = TaskRetriever(cwd, store)
    retriever.seed_completed_task(task.id)
    snapshot = CommittedResearchSnapshot(
        task_id=task.id,
        version=1,
        asset_manifest=[
            AssetRevisionRef(
                asset_type="document",
                logical_id=first.id,
                revision_id=first.id,
                content_sha256=first.text_sha256,
                task_id=task.id,
            )
        ],
        fingerprint="f" * 64,
        created_at="2026-01-01T00:00:00+00:00",
    )

    passages = retriever.retrieve(task.id, "launch", snapshot=snapshot)

    assert passages
    assert all(item.document_id == first.id for item in passages)
