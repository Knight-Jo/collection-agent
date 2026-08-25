"""Validation tests for persistent conversational state models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from intel_agent.models import (
    ActionRequest,
    CitationDraft,
    Conversation,
    Message,
    MessageCitation,
    MessageProcessingAttempt,
    ReportVersion,
    ResearchBrief,
    ResearchCheckpoint,
    ResearchRun,
    TimelineEntry,
)

NOW = "2026-08-25T00:00:00+00:00"


def test_conversation_lifecycle_allows_intake_without_task():
    intake = Conversation(
        id="conversation-1",
        task_id=None,
        status="intake",
        title="新对话",
        created_at=NOW,
        updated_at=NOW,
    )
    assert intake.task_id is None

    with pytest.raises(ValidationError):
        intake.model_copy(update={"status": "active"}).model_validate(
            {**intake.model_dump(), "status": "active"}
        )


def test_research_brief_has_versioned_minimal_contract():
    brief = ResearchBrief(topic="先进封装", key_questions=["竞争格局？"])
    assert brief.schema_version == "1"
    assert brief.requested_outputs == ["research_report"]


def test_processing_attempt_and_timeline_have_independent_sequences():
    attempt = MessageProcessingAttempt(
        id="attempt-1",
        user_message_id="message-1",
        attempt=1,
        status="accepted",
        started_at=NOW,
    )
    entry = TimelineEntry(
        id="timeline-1",
        conversation_id="conversation-1",
        timeline_sequence=7,
        source_event_sequence=11,
        entry_type="message",
        data={},
        created_at=NOW,
    )
    assert attempt.attempt == 1
    assert entry.timeline_sequence != entry.source_event_sequence


def test_user_message_requires_client_message_id():
    with pytest.raises(ValidationError):
        Message(
            id="msg-1",
            conversation_id="conversation-1",
            epoch_id="epoch-1",
            sequence=1,
            role="user",
            content="继续搜索",
            status="accepted",
            created_at=NOW,
        )


def test_assistant_message_is_complete_reply():
    message = Message(
        id="msg-2",
        conversation_id="conversation-1",
        epoch_id="epoch-1",
        sequence=2,
        role="assistant",
        content="回答",
        status="completed",
        reply_to_id="msg-1",
        created_at=NOW,
        completed_at=NOW,
    )

    assert message.client_message_id is None

    with pytest.raises(ValidationError):
        Message.model_validate(
            {**message.model_dump(), "status": "processing"}
        )


def test_proposed_action_has_no_request_fields():
    action = ActionRequest(
        id="action-1",
        task_id="task-1",
        trigger_message_id="msg-1",
        action_type="continue_research",
        immutable_payload={"question_ids": ["q-1"]},
        precondition_committed_state_version=0,
        status="proposed",
        created_at=NOW,
    )

    assert action.request_mode is None
    assert action.request_message_id is None


def test_queued_action_requires_request_fields():
    with pytest.raises(ValidationError):
        ActionRequest(
            id="action-1",
            task_id="task-1",
            trigger_message_id="msg-1",
            action_type="continue_research",
            immutable_payload={},
            precondition_committed_state_version=0,
            status="queued",
            created_at=NOW,
        )


def test_terminal_run_requires_completion_time():
    with pytest.raises(ValidationError):
        ResearchRun(
            id="run-1",
            task_id="task-1",
            run_type="continue_research",
            input_committed_state_version=0,
            input_snapshot={},
            status="succeeded",
            created_at=NOW,
            started_at=NOW,
        )


def test_stopping_run_is_non_terminal_and_leased():
    run = ResearchRun(
        id="run-1",
        task_id="task-1",
        run_type="initial",
        input_committed_state_version=0,
        input_snapshot={},
        status="stopping",
        created_at=NOW,
        started_at=NOW,
        lease_owner="runtime-1",
        lease_expires_at=NOW,
    )
    assert run.completed_at is None


def test_committed_checkpoint_requires_output_version_and_time():
    with pytest.raises(ValidationError):
        ResearchCheckpoint(
            id="checkpoint-1",
            task_id="task-1",
            research_run_id="run-1",
            sequence=1,
            input_committed_state_version=0,
            status="committed",
            reason="final",
            started_at=NOW,
        )


def test_published_report_requires_publication_time():
    with pytest.raises(ValidationError):
        ReportVersion(
            id="report-1",
            task_id="task-1",
            version=1,
            status="published",
            content_path="output/report.md",
            content_sha256="abc",
            based_on_committed_state_version=0,
            created_at=NOW,
        )


def test_report_requires_checkpoint_identity():
    report = ReportVersion(
        id="report-1",
        task_id="task-1",
        version=1,
        status="draft",
        content_path="output/report.md",
        content_sha256="abc",
        based_on_checkpoint_id="checkpoint-7",
        based_on_committed_state_version=19,
        created_at=NOW,
    )
    assert report.based_on_checkpoint_id == "checkpoint-7"


def test_citation_draft_validates_line_range():
    with pytest.raises(ValidationError):
        CitationDraft(
            citation_kind="verified_evidence",
            document_id="document-1",
            evidence_id="evidence-1",
            title="材料",
            source_url="https://example.com/source",
            quote_text="引用",
            line_start=8,
            line_end=3,
            source_content_hash="abc",
        )


def test_message_citation_extends_citation_draft():
    citation = MessageCitation(
        id="citation-1",
        task_id="task-1",
        message_id="message-1",
        sequence=1,
        citation_kind="material_clue",
        document_id="document-1",
        title="材料",
        source_url="https://example.com/source",
        quote_text="引用",
        line_start=1,
        line_end=2,
        source_content_hash="abc",
        created_at=NOW,
    )

    assert citation.evidence_id is None
    assert citation.fact_id is None
