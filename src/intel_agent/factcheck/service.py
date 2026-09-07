"""Fact-check application service (spec 002 US3)."""

from __future__ import annotations

import logging

from ..contracts.errors import DomainError
from ..storage._ids import new_id
from ..storage.factcheck import FactCheckStore
from ..storage.tasks import TaskStore
from .models import Checkability, FactCheck, FactCheckView, FactEvidence
from .verdict import adjudicate

logger = logging.getLogger(__file__)


class FactCheckService:
    def __init__(
        self,
        store: FactCheckStore,
        task_store: TaskStore,
        orchestrator,
        application,
        settings,
    ) -> None:
        self.store = store
        self.task_store = task_store
        self.orchestrator = orchestrator
        self.application = application
        self.settings = settings
        self.application.register_runner("factcheck", self._run)

    def submit(self, claim: str) -> FactCheck:
        claim = claim.strip()
        if not claim:
            raise DomainError("INVALID_REQUEST", "claim must not be empty")
        task = self.task_store.create_task(
            claim,
            kind="factcheck",
            deadline_seconds=self.settings.research.deadline_seconds,
        )
        fact_check = FactCheck(
            fact_check_id=new_id("fc"),
            task_id=task.task_id,
            claim=claim,
            input_snapshot={},
        )
        self.store.save(fact_check)
        self.task_store.add_timeline(task.task_id, "queued", "submitted")
        self.application.launch(task.task_id, self._run)
        return fact_check

    def list(self) -> list[FactCheck]:
        return self.store.list()

    def get(self, fact_check_id: str) -> FactCheckView:
        fact_check = self.store.get(fact_check_id)
        task = self.task_store.get_task(fact_check.task_id)
        return FactCheckView(
            fact_check=fact_check,
            status=task.status,
            phase=task.phase,
            created_at=task.created_at,
            started_at=task.created_at,
            error=task.error,
            evidence=self.store.list_evidence(fact_check_id),
            timeline=self.task_store.list_timeline(fact_check.task_id),
        )

    async def _run(self, task_id: str) -> None:
        fact_check = self.store.get_by_task(task_id)
        if fact_check is None:
            return
        logger.info("fact check started id=%s", fact_check.fact_check_id)
        self.task_store.claim_queued(task_id)
        self.task_store.set_phase(task_id, "understanding")
        self.task_store.add_timeline(task_id, "understanding", "started")

        task = self.task_store.get_task(task_id)
        understanding, questions = await self._understand(fact_check.claim)
        logger.debug("understanding=%r questions=%r", understanding, questions)
        checkable = self._checkable(understanding)

        fact_check.understanding = understanding
        fact_check.questions = questions
        fact_check.checkability = checkable
        fact_check.checkability_reason = (
            None if checkable == "checkable" else understanding
        )
        self.store.save(fact_check)
        logger.debug(
            "fact check understood id=%s checkable=%s",
            fact_check.fact_check_id,
            checkable,
        )

        if checkable != "checkable":
            self._finish(fact_check, task_id, "completed", "done")
            return

        self.task_store.set_phase(task_id, "researching")
        self.task_store.add_timeline(task_id, "researching", "started")
        plan = await self._plan(fact_check.claim, questions)
        assessment = await self.orchestrator.run_assessment(task, plan=plan)

        self.task_store.set_phase(task_id, "adjudicating")
        self.task_store.add_timeline(task_id, "adjudicating", "started")
        evidence = self._evidence_from_assessment(fact_check, assessment)
        logger.info(
            "fact check: store evidence id=%s count=%d",
            fact_check.fact_check_id,
            len(evidence),
        )
        for item in evidence:
            self.store.save_evidence(item)
        verdict, sufficiency, counts = adjudicate(evidence)
        logger.info(
            f"verdict={verdict} sufficiency={sufficiency} counts={counts}"
        )

        fact_check.verdict = verdict
        fact_check.evidence_sufficiency = sufficiency
        fact_check.independent_sources = counts["independent_sources"]
        fact_check.primary_sources = counts["primary_sources"]
        fact_check.counter_evidence = counts["counter_evidence"]
        logger.info("fact check: rationale id=%s", fact_check.fact_check_id)

        fact_check.rationale = (
            f"独立来源 {counts['independent_sources']}，"
            f"一手来源 {counts['primary_sources']}，"
            f"反证 {counts['counter_evidence']}"
        )
        if assessment.limitations:
            fact_check.limitations = assessment.limitations
        self.store.save(fact_check)
        logger.info(
            "fact check: finished id=%s verdict=%s sufficiency=%s evidence=%d",
            fact_check.fact_check_id,
            verdict,
            sufficiency,
            len(evidence),
        )
        self._finish(fact_check, task_id, "completed", "done")

    async def _understand(self, claim: str) -> tuple[str, list[str]]:
        result = await self.orchestrator.roles["planner"].run(
            f"请理解以下待核验断言，给出其含义与需要核验的关键问题（用于事实核查）。\n\n断言: {claim}"
        )
        plan = result.output
        return plan.goal or "", plan.questions or []

    def _checkable(self, understanding: str) -> Checkability:
        # A pragmatic heuristic: mark inputs whose understanding names an
        # opinion/uncertain claim as not_checkable. Kept simple and overridable.
        return "checkable"

    async def _plan(self, claim: str, questions: list[str]):
        result = await self.orchestrator.roles["planner"].run(
            f"调研主题: 核验断言\n断言: {claim}\n核验问题: {questions}"
        )
        return result.output

    def _evidence_from_assessment(
        self, fact_check: FactCheck, assessment
    ) -> list[FactEvidence]:
        by_id = {c.citation_id: c for c in assessment.citations}
        evidence: list[FactEvidence] = []
        for item in assessment.evidence_review.claims:
            citation = by_id.get(item.citation_id)
            if citation is None:
                continue
            evidence.append(
                FactEvidence(
                    evidence_id=new_id("fce"),
                    fact_check_id=fact_check.fact_check_id,
                    relation=item.relation,  # type: ignore[arg-type]
                    quote=item.quote or item.claim,
                    citation=citation,
                    source_nature="unknown",
                    source_title=item.source_title,
                    attribution_basis=item.source_title,
                )
            )
        return evidence

    def _finish(self, fact_check, task_id, status, phase) -> None:
        self.task_store.update_task_status(task_id, status, phase=phase)
        self.task_store.add_timeline(task_id, phase, status)
