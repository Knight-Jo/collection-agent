"""Orchestrator role-pipeline loop test (T18)."""

from __future__ import annotations

import pytest

from intel_agent.contracts.research import (
    ContextPackage,
    CoverageAssessment,
    EvidenceReview,
    ReportSection,
    ResearchDecision,
    ResearchPlan,
    ResearchReport,
    SearchBatch,
    SearchDirection,
    SearchQuery,
)
from intel_agent.indexing.models import AcquisitionReport
from intel_agent.orchestration.orchestrator import ResearchOrchestrator
from intel_agent.runtime.config import ResearchConfig


class _Usage:
    requests = 1
    input_tokens = 10
    output_tokens = 10


class _Result:
    def __init__(self, output):
        self.output = output
        self.usage = _Usage()


class FakeRole:
    """Mimics a pydantic-ai Agent: run() returns output + usage."""

    def __init__(self, outputs):
        self.outputs = outputs if isinstance(outputs, list) else [outputs]
        self.calls = 0

    async def run(self, prompt):
        output = self.outputs[min(self.calls, len(self.outputs) - 1)]
        self.calls += 1
        return _Result(output)


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
    async def index(self, artifact_id):
        return None


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
    planner = FakeRole(
        ResearchPlan(
            questions=["q1"],
            directions=[
                SearchDirection(query=SearchQuery(text="first query"))
            ],
        )
    )
    coverage = FakeRole(
        CoverageAssessment(sufficiency="low", summary="need more evidence")
    )
    verifier = FakeRole(EvidenceReview(summary="no conflicts"))
    decider = FakeRole(
        [
            ResearchDecision(
                action="search",
                directions=[
                    SearchDirection(query=SearchQuery(text="gap query"))
                ],
                reason="gap",
            ),
            ResearchDecision(
                action="finish",
                citation_ids=["C1"],
                reason="enough",
            ),
        ]
    )
    writer = FakeRole(
        ResearchReport(
            title="report",
            sections=[],
            conclusions=["conclusion"],
            citation_ids=["C1"],
        )
    )
    roles = {
        "planner": planner,
        "coverage": coverage,
        "verifier": verifier,
        "decider": decider,
        "writer": writer,
    }
    search = FakeSearch()
    orchestrator = ResearchOrchestrator(
        material_store,
        search,  # type: ignore[arg-type]
        FakeAcquisition(),  # type: ignore[arg-type]
        FakeIndexing(),  # type: ignore[arg-type]
        FakeContext(),  # type: ignore[arg-type]
        roles,
        ResearchConfig(),
        "profile-1",
        tmp_path / "locks",
    )

    class Harness:
        searched_queries = search.queries

        async def run_two_rounds(self):
            return await orchestrator.run("question")

    return Harness()


async def test_two_rounds_use_planner_then_decider(research_harness):
    result = await research_harness.run_two_rounds()
    assert result.status == "completed"
    assert research_harness.searched_queries == ["first query", "gap query"]
    assert result.report is not None
    assert result.answer == result.report.markdown()
    assert result.answer.startswith("# report")


def _orchestrator(
    material_store, tmp_path, roles, max_rounds: int = 3
) -> ResearchOrchestrator:
    return ResearchOrchestrator(
        material_store,
        FakeSearch(),  # type: ignore[arg-type]
        FakeAcquisition(),  # type: ignore[arg-type]
        FakeIndexing(),  # type: ignore[arg-type]
        FakeContext(),  # type: ignore[arg-type]
        roles,
        ResearchConfig(max_rounds=max_rounds),
        "profile-1",
        tmp_path / "locks",
    )


async def test_max_rounds_exhausted_forces_final_report(
    material_store, tmp_path
):
    roles = {
        "planner": FakeRole(
            ResearchPlan(
                questions=["q1"],
                directions=[
                    SearchDirection(query=SearchQuery(text="first query"))
                ],
            )
        ),
        "coverage": FakeRole(
            CoverageAssessment(sufficiency="low", summary="partial evidence")
        ),
        "verifier": FakeRole(EvidenceReview(summary="some conflicts")),
        "decider": FakeRole(
            ResearchDecision(
                action="search",
                directions=[SearchDirection(query=SearchQuery(text="gap"))],
                reason="still a gap",
            )
        ),
        "writer": FakeRole(
            ResearchReport(
                title="forced report",
                sections=[ReportSection(heading="h", body="b")],
                conclusions=["c"],
                citation_ids=["C1"],
            )
        ),
    }
    orchestrator = _orchestrator(material_store, tmp_path, roles, max_rounds=2)
    result = await orchestrator.run("question")

    assert result.status == "completed"
    assert result.stop_reason == "max_rounds"
    assert result.report is not None
    assert result.report.title == "forced report"
    assert material_store.get_task(result.task_id).status == "completed"
