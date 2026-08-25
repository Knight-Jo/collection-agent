"""Validation tests for persistent conversational state models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from intel_agent.models import (
    ActionRequest,
    Message,
    ReportVersion,
    ResearchCheckpoint,
    ResearchRun,
)

NOW = "2026-08-25T00:00:00+00:00"


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
