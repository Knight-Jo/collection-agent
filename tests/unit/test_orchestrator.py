"""Orchestrator two-round loop test (T18)."""

from __future__ import annotations

import pytest

from intel_agent.contracts.research import (
    ContextPackage,
    ResearchDecision,
    SearchBatch,
    SearchQuery,
)
from intel_agent.indexing.models import AcquisitionReport
from intel_agent.orchestration.orchestrator import ResearchOrchestrator
from intel_agent.runtime.config import ResearchConfig


class FakeAgent:
    def __init__(self, decisions):
        self.decisions = decisions
        self.actions = []
        self._i = 0

    async def decide(self, task, context):
        decision = self.decisions[min(self._i, len(self.decisions) - 1)]
        self.actions.append(decision.action)
        self._i += 1
        return decision

    async def decide_with_repair(self, task, context):
        return await self.decide(task, context)


class FakeSearch:
    def __init__(self):
        self.queries = []

    async def search(self, request):
        self.queries.append(request.query.text)
        return SearchBatch(hits=[], provider_reports=[], status="success")


class FakeAcquisition:
    async def acquire(
        self, task_id, source, profile_id, index_after_store=False
    ):
        return AcquisitionReport(
            task_id=task_id,
            work_item_id="wi",
            artifact_id="art-1",
            stage="done",
            status="success",
        )


class FakeIndexing:
    def __init__(self):
        self.calls = 0

    async def index(self, artifact_id):
        self.calls += 1


class FakeContext:
    async def build(self, request):
        from intel_agent.contracts.documents import Citation

        return ContextPackage(
            task_id=request.task_id,
            query=request.query,
            scope_id="s",
            citations=[
                Citation(
                    citation_id="C1",
                    chunk_id="chk1",
                    artifact_id="art1",
                    document_id="doc1",
                    revision_id="rev1",
                    resource_id="res1",
                )
            ],
        )


@pytest.fixture
def research_harness(material_store, tmp_path):
    decisions = [
        ResearchDecision(
            action="search",
            queries=[SearchQuery(text="first query")],
            source_types=["web"],
            reason="start",
        ),
        ResearchDecision(
            action="search",
            queries=[SearchQuery(text="gap query")],
            source_types=["web"],
            reason="gap",
        ),
        ResearchDecision(
            action="finish",
            queries=[],
            draft_answer="an answer",
            reason="enough",
        ),
    ]
    agent = FakeAgent(decisions)
    search = FakeSearch()
    indexing = FakeIndexing()
    orchestrator = ResearchOrchestrator(
        material_store,
        search,
        FakeAcquisition(),
        indexing,
        FakeContext(),
        agent,
        ResearchConfig(),
        "profile-1",
        tmp_path / "locks",
    )

    class Harness:
        decision_actions = agent.actions
        searched_queries = search.queries

        async def run_two_rounds(self):
            return await orchestrator.run("question")

    return Harness()


async def test_two_rounds_do_not_replan_after_evaluate(research_harness):
    result = await research_harness.run_two_rounds()
    assert result.status == "completed"
    assert research_harness.decision_actions == ["search", "search", "finish"]
    assert research_harness.searched_queries == ["first query", "gap query"]
