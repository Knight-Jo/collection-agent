"""Dedicated report agent tests."""

import asyncio
import json

import pytest

from intel_agent.audit import audit_task_evidence
from intel_agent.config import Settings
from intel_agent.coverage import eval_coverage
from intel_agent.fact import save_fact
from intel_agent.models import IntelError, ResearchReportedConclusion
from intel_agent.report_agent import (
    ReportAgent,
    _build_payload,
    _parse_report_input,
)
from tests.conftest import fake_judge, make_document, new_task, save_evidence


def test_parse_report_input_accepts_json():
    draft = _parse_report_input(
        '{"sections": [{"question_id": "q1", "conclusions": []}], '
        '"overall_conclusions": []}'
    )

    assert draft.sections[0].question_id == "q1"
    assert draft.overall_conclusions == []


def test_parse_report_input_strips_code_fences():
    draft = _parse_report_input(
        '```json\n{"sections": [], "overall_conclusions": []}\n```'
    )

    assert draft.sections == []


def test_parse_report_input_rejects_garbage():
    with pytest.raises(IntelError):
        _parse_report_input("not json")


def test_parse_report_input_rejects_wrong_schema():
    with pytest.raises(IntelError):
        _parse_report_input('{"foo": 1}')


def test_build_payload_includes_facts_and_coverage_status(cwd):
    task = new_task(cwd)
    fact = save_fact(cwd, task.id, task.questions[0].id, "已审核的公开事实")
    document = make_document(cwd, "已审核的公开事实")
    save_evidence(cwd, fact.id, document.id, "supports", fact.statement)
    asyncio.run(audit_task_evidence(cwd, task.id, fake_judge, "test", "fake"))
    coverage = eval_coverage(cwd, task.id)

    payload = _build_payload(task, coverage, [fact], None)

    assert payload["facts"][0]["fact_id"] == fact.id
    assert payload["facts"][0]["coverage_status"] in (
        "covered",
        "partial",
        "gap",
    )
    assert payload["coverage"]["level"] in (
        "sufficient",
        "mostly_sufficient",
        "insufficient",
    )


def test_compose_for_task_parses_report_agent_output(cwd, monkeypatch):
    task = new_task(cwd)
    fact = save_fact(cwd, task.id, task.questions[0].id, "已审核的公开事实")
    document = make_document(cwd, "已审核的公开事实")
    save_evidence(cwd, fact.id, document.id, "supports", fact.statement)
    asyncio.run(audit_task_evidence(cwd, task.id, fake_judge, "test", "fake"))
    eval_coverage(cwd, task.id)

    settings = Settings()
    agent = ReportAgent(
        settings.model, settings.model_api_key(), settings.context
    )

    class _FakeRun:
        output = json.dumps(
            {
                "sections": [
                    {
                        "question_id": task.questions[0].id,
                        "conclusions": [
                            {"kind": "reported", "fact_id": fact.id}
                        ],
                    }
                ],
                "overall_conclusions": [],
            },
            ensure_ascii=False,
        )

    async def fake_run(_prompt):
        return _FakeRun()

    monkeypatch.setattr(agent.agent, "run", fake_run)

    draft = asyncio.run(agent.compose_for_task(cwd, task.id))

    assert draft.sections[0].question_id == task.questions[0].id
    conclusion = draft.sections[0].conclusions[0]
    assert isinstance(conclusion, ResearchReportedConclusion)
    assert conclusion.fact_id == fact.id
