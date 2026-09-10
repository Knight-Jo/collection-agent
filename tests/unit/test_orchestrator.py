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
    def __init__(self):
        self.queries: list[str] = []
        self.merges = 0

    def merge_packages(self, task_id, query, packages, max_tokens):
        # keep the first package's citations; enough for loop-level fakes
        self.merges += 1
        return packages[0]

    async def build(self, request):
        self.queries.append(request.query)
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
def research_harness(material_store, task_store, tmp_path):
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
        task_store=task_store,
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
    material_store, task_store, tmp_path, roles, max_rounds: int = 3
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
        task_store=task_store,
    )


async def test_max_rounds_exhausted_forces_final_report(
    material_store, task_store, tmp_path
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
    orchestrator = _orchestrator(
        material_store, task_store, tmp_path, roles, max_rounds=2
    )
    result = await orchestrator.run("question")

    assert result.status == "completed"
    assert result.stop_reason == "max_rounds"
    assert result.report is not None
    assert result.report.title == "forced report"
    assert task_store.get_task(result.task_id).status == "completed"


def test_question_batches_grouping():
    from intel_agent.orchestration.orchestrator import question_batches

    assert question_batches(["a", "b", "c", "d", "e"], 2) == [
        ["a", "b"],
        ["c", "d"],
        ["e"],
    ]
    assert question_batches(["a"], 2) == [["a"]]
    assert question_batches(["a", "b"], 5) == [["a", "b"]]


def test_weak_questions_filter_and_fallback():
    from intel_agent.contracts.research import (
        CoverageAssessment,
        QuestionCoverage,
    )
    from intel_agent.orchestration.orchestrator import weak_questions

    questions = ["战场态势", "军援规模", "制裁执行"]
    coverage = CoverageAssessment(
        sufficiency="low",
        questions=[
            QuestionCoverage(
                question_id="Q1", question="战场态势", status="answered"
            ),
            QuestionCoverage(
                question_id="Q2", question="军援规模", status="blocked"
            ),
            QuestionCoverage(
                question_id="Q3", question="制裁执行", status="researching"
            ),
        ],
    )
    assert weak_questions(questions, coverage) == ["军援规模", "制裁执行"]

    all_answered = CoverageAssessment(
        sufficiency="high",
        questions=[
            QuestionCoverage(
                question_id=f"Q{i + 1}", question=q, status="answered"
            )
            for i, q in enumerate(questions)
        ],
    )
    # empty filter falls back to every question, never a blank build
    assert weak_questions(questions, all_answered) == questions


async def test_per_question_context_builds_batched_queries(
    material_store, task_store, tmp_path
):
    plan = ResearchPlan(
        questions=["战场态势", "军援规模", "制裁执行"],
        directions=[SearchDirection(query=SearchQuery(text="q"))],
    )
    decider = FakeRole(
        ResearchDecision(action="finish", citation_ids=["C1"], reason="enough")
    )
    roles = {
        "planner": FakeRole(plan),
        "coverage": FakeRole(CoverageAssessment(sufficiency="high")),
        "verifier": FakeRole(EvidenceReview(summary="ok")),
        "decider": decider,
        "writer": FakeRole(
            ResearchReport(title="t", conclusions=["c"], citation_ids=["C1"])
        ),
    }
    context = FakeContext()
    orchestrator = ResearchOrchestrator(
        material_store,
        FakeSearch(),  # type: ignore[arg-type]
        FakeAcquisition(),  # type: ignore[arg-type]
        FakeIndexing(),  # type: ignore[arg-type]
        context,  # type: ignore[arg-type]
        roles,
        ResearchConfig(per_question_context=True, questions_per_context=2),
        "profile-1",
        tmp_path / "locks",
        task_store=task_store,
    )
    task = task_store.create_task("俄罗斯乌克兰战争三年情况")
    await orchestrator.run_task(task)
    # three questions in batches of two -> two question-driven queries
    assert "战场态势 军援规模" in context.queries
    assert "制裁执行" in context.queries
    assert context.merges >= 1
