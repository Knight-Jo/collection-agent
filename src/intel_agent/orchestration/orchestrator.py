"""ResearchOrchestrator: deterministic research loop (spec §12)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from ..contracts.research import (
    BudgetUsage,
    Checkpoint,
    ContextPackage,
    ContextRequest,
    ResearchDecision,
    ResearchResult,
    ResearchTask,
    SearchRequest,
)
from ..runtime.config import ResearchConfig
from ..storage.materials import MaterialStore
from .state import TaskLock


class ResearchOrchestrator:
    def __init__(
        self,
        store: MaterialStore,
        search_service,
        acquisition_pipeline,
        indexing_service,
        context_manager,
        agent,
        config: ResearchConfig,
        profile_id: str,
        lock_dir: Path,
        context_max_tokens: int = 8000,
    ) -> None:
        self.store = store
        self.search_service = search_service
        self.acquisition_pipeline = acquisition_pipeline
        self.indexing_service = indexing_service
        self.context_manager = context_manager
        self.agent = agent
        self.config = config
        self.profile_id = profile_id
        self.lock_dir = lock_dir
        self.context_max_tokens = context_max_tokens

    async def run(self, question: str) -> ResearchResult:
        task = self.store.create_task(
            question, deadline_seconds=self.config.deadline_seconds
        )
        return await self._run_task(task)

    async def resume(self, task_id: str) -> ResearchResult:
        task = self.store.get_task(task_id)
        return await self._run_task(task)

    async def _run_task(self, task: ResearchTask) -> ResearchResult:
        lock = TaskLock(self.lock_dir, task.task_id)
        lock.acquire()
        try:
            self.store.get_task(task.task_id)
            context = ContextPackage(
                task_id=task.task_id, query=task.question, scope_id="",
            )
            accepted: list[str] = []
            round_no = task.round
            for _ in range(self.config.max_rounds):
                decision = await self.agent.decide(task, context)
                if decision.action == "finish":
                    result = ResearchResult(
                        task_id=task.task_id,
                        status="completed",
                        answer=decision.draft_answer or "",
                        stop_reason="evidence_sufficient",
                        usage=task.budget_used,
                    )
                    self._save_checkpoint(task, round_no, accepted, result)
                    return result
                for query in decision.queries:
                    batch = await self.search_service.search(
                        SearchRequest(
                            query=query,
                            per_provider_limit=10,
                            total_limit=10,
                        )
                    )
                    for hit in batch.hits:
                        report = await self.acquisition_pipeline.acquire(
                            task.task_id, hit, self.profile_id
                        )
                        if report.artifact_id:
                            accepted.append(report.artifact_id)
                            await self.indexing_service.index(
                                report.artifact_id
                            )
                round_no += 1
                task.round = round_no
                context = await self.context_manager.build(
                    ContextRequest(
                        task_id=task.task_id,
                        query=task.question,
                        max_tokens=self.context_max_tokens,
                    )
                )
                self._save_checkpoint(task, round_no, accepted, None)
            result = ResearchResult(
                task_id=task.task_id, status="partial",
                answer="", stop_reason="max_rounds",
                limitations=["max rounds reached"],
                usage=task.budget_used,
            )
            self._save_checkpoint(task, round_no, accepted, result)
            return result
        finally:
            lock.release()

    def _save_checkpoint(self, task, round_no, accepted, result) -> None:
        checkpoint = Checkpoint(
            task_id=task.task_id,
            round=round_no,
            accepted_artifact_ids=accepted,
            budget_used=task.budget_used,
            stop_reason=result.stop_reason if result else None,
            updated_at=datetime.now(UTC),
        )
        self.store.save_checkpoint(
            task.task_id, checkpoint, task.budget_used
        )
