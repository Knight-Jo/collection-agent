"""ResearchOrchestrator: role-based research loop (spec §12)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..acquisition import AcquisitionPipeline
from ..context.manager import ContextManager
from ..contracts.research import (
    BudgetUsage,
    Checkpoint,
    ContextPackage,
    ContextRequest,
    ResearchDecision,
    ResearchPlan,
    ResearchResult,
    ResearchTask,
    SearchDirection,
    SearchQuery,
    SearchRequest,
)
from ..indexing.service import IndexingService
from ..runtime.config import ResearchConfig
from ..search.service import SearchService
from ..storage.materials import MaterialStore
from .state import TaskLock

EventSink = Callable[[dict], Awaitable[None]]


def _evidence_block(context: ContextPackage) -> str:
    citations = "\n".join(
        f"[{c.citation_id}] {c.source_url or c.document_id}"
        for c in context.citations
    )
    return f"证据材料:\n{context.formatted_text}\n\n可用引用编号:\n{citations}"


def _questions_block(plan: ResearchPlan) -> str:
    return "\n".join(f"Q{i + 1}. {q}" for i, q in enumerate(plan.questions))


class ResearchOrchestrator:
    """Coordinate the role-based research loop for a research task.

    The orchestrator plans search directions, collects and indexes sources,
    evaluates evidence, and either requests another round or writes a report.
    Progress and budget usage are persisted through the store so a task can be
    resumed and checkpointed between rounds.

    Attributes:
        store: Persists tasks, materials, budget usage, and checkpoints.
        search_service: Executes searches for the planned directions.
        acquisition_pipeline: Fetches, extracts, stores, and prepares sources.
        indexing_service: Indexes acquired artifacts for retrieval.
        context_manager: Builds evidence context for agent evaluation.
        roles: Planner, coverage, verifier, decider, and writer agents.
        config: Limits and runtime settings for the research loop.
        profile_id: Default extraction profile for acquired sources.
        lock_dir: Directory used to prevent concurrent runs of one task.
        context_max_tokens: Maximum tokens included in evidence context.
        search_per_provider_limit: Maximum results requested per provider.
        search_total_limit: Maximum results requested per search round.
        event_sink: Optional default destination for progress events.
    """

    def __init__(
        self,
        store: MaterialStore,
        search_service: SearchService,
        acquisition_pipeline: AcquisitionPipeline,
        indexing_service: IndexingService,
        context_manager: ContextManager,
        roles: dict[str, Any],
        config: ResearchConfig,
        profile_id: str,
        lock_dir: Path,
        context_max_tokens: int = 8000,
        search_per_provider_limit: int = 10,
        search_total_limit: int = 20,
        event_sink: EventSink | None = None,
    ) -> None:
        self.store = store
        self.search_service = search_service
        self.acquisition_pipeline = acquisition_pipeline
        self.indexing_service = indexing_service
        self.context_manager = context_manager
        self.roles = roles
        self.config = config
        self.profile_id = profile_id
        self.lock_dir = lock_dir
        self.context_max_tokens = context_max_tokens
        self.search_per_provider_limit = search_per_provider_limit
        self.search_total_limit = search_total_limit
        self.event_sink = event_sink

    async def _emit(self, sink: EventSink | None, event: dict) -> None:
        if sink is not None:
            await sink(event)

    async def _run_agent(self, agent, prompt: str, task_id: str) -> Any:
        result = await agent.run(prompt)
        usage = result.usage
        self.store.record_budget_change(
            task_id,
            BudgetUsage(
                llm_calls=usage.requests,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
            ),
        )
        return result.output

    async def run(self, question: str) -> ResearchResult:
        """Create and execute a new research task for ``question``.

        Args:
            question: Research question to investigate.

        Returns:
            The completed or partial research result.
        """
        task = self.store.create_task(
            question, deadline_seconds=self.config.deadline_seconds
        )
        return await self.run_task(task)

    async def resume(self, task_id: str) -> ResearchResult:
        """Resume and execute an existing research task.

        Args:
            task_id: Identifier of the task to resume.

        Returns:
            The completed or partial research result.
        """
        task = self.store.get_task(task_id)
        return await self.run_task(task)

    async def run_task(
        self,
        task: ResearchTask,
        event_sink: EventSink | None = None,
        plan: ResearchPlan | None = None,
    ) -> ResearchResult:
        """Execute a task through planning, research rounds, and reporting.

        Each round searches in the current directions, acquires new materials,
        assesses coverage and evidence, then decides whether to continue or
        finish. A checkpoint is saved after each round and before returning.

        Args:
            task: Task to execute.
            event_sink: Optional per-run event destination, overriding the
                configured default sink.
            plan: Optional existing plan; when omitted, the planner role creates
                one from the task question.

        Returns:
            A completed result when evidence is sufficient, or a partial result
            when the configured round limit is reached.
        """
        sink = event_sink or self.event_sink
        lock = TaskLock(self.lock_dir, task.task_id)
        lock.acquire()
        try:
            context = ContextPackage(
                task_id=task.task_id, query=task.question, scope_id=""
            )
            accepted: list[str] = []
            round_no = task.round
            last_summary = ""
            await self._emit(
                sink,
                {
                    "event": "run.status",
                    "task_id": task.task_id,
                    "status": "running",
                },
            )
            await self._emit(
                sink,
                {
                    "event": "run.phase",
                    "task_id": task.task_id,
                    "phase": "planning",
                },
            )
            await self._emit(
                sink,
                {
                    "event": "timeline",
                    "task_id": task.task_id,
                    "kind": "intent",
                    "label": "理解调研目标",
                    "detail": "拆解关键问题并确认范围",
                },
            )
            if plan is None:
                plan = await self._run_agent(
                    self.roles["planner"], task.question, task.task_id
                )
            assert plan is not None
            directions = plan.directions or [
                SearchDirection(query=SearchQuery(text=task.question))
            ]
            for _ in range(self.config.max_rounds):
                await self._emit(
                    sink,
                    {
                        "event": "timeline",
                        "task_id": task.task_id,
                        "kind": "search_plan",
                        "label": "生成检索计划",
                        "detail": f"规划 {len(directions)} 组检索方向",
                    },
                )
                await self._emit(
                    sink,
                    {
                        "event": "run.phase",
                        "task_id": task.task_id,
                        "phase": "collecting",
                    },
                )
                round_materials = 0
                for direction_index, direction in enumerate(directions, 1):
                    query = direction.query.text
                    reason = direction.reason or "按规划方向检索"
                    providers = (
                        ", ".join(direction.provider_names)
                        if direction.provider_names
                        else "全部可用来源"
                    )
                    await self._emit(
                        sink,
                        {
                            "event": "timeline",
                            "task_id": task.task_id,
                            "kind": "search_plan",
                            "label": (
                                f"执行检索方向 {direction_index}/"
                                f"{len(directions)}"
                            ),
                            "detail": (
                                f"{query}；{reason}；来源：{providers}"
                            ),
                        },
                    )
                    batch = await self.search_service.search(
                        SearchRequest(
                            query=direction.query,
                            provider_names=direction.provider_names,
                            per_provider_limit=self.search_per_provider_limit,
                            total_limit=self.search_total_limit,
                        )
                    )
                    await self._emit(
                        sink,
                        {
                            "event": "timeline",
                            "task_id": task.task_id,
                            "kind": "search",
                            "label": "执行检索",
                            "detail": f"命中 {len(batch.hits)} 个来源",
                        },
                    )
                    for hit in batch.hits:
                        if (
                            len(accepted) >= self.config.new_resources_per_task
                            or round_materials
                            >= self.config.new_resources_per_round
                        ):
                            break
                        report = await self.acquisition_pipeline.acquire(
                            task.task_id, hit, self.profile_id
                        )
                        if report.artifact_id:
                            accepted.append(report.artifact_id)
                            round_materials += 1
                            await self._emit(
                                sink,
                                {
                                    "event": "material",
                                    "task_id": task.task_id,
                                    "title": hit.title or hit.url,
                                    "url": hit.url,
                                    "source_type": (
                                        hit.source_types[0]
                                        if hit.source_types
                                        else "web"
                                    ),
                                },
                            )
                            await self._emit(
                                sink,
                                {
                                    "event": "timeline",
                                    "task_id": task.task_id,
                                    "kind": "material",
                                    "label": "材料入库",
                                    "detail": "抓取并提取 1 份材料",
                                },
                            )
                            try:
                                await self.indexing_service.index(
                                    report.artifact_id
                                )
                            except Exception:  # noqa: BLE001
                                continue
                round_no += 1
                task.round = round_no
                await self._emit(
                    sink,
                    {
                        "event": "run.phase",
                        "task_id": task.task_id,
                        "phase": "assessing",
                    },
                )
                context = await self.context_manager.build(
                    ContextRequest(
                        task_id=task.task_id,
                        query=task.question,
                        max_tokens=self.context_max_tokens,
                    )
                )
                evidence_block = _evidence_block(context)
                questions = _questions_block(plan)
                await self._emit(
                    sink,
                    {
                        "event": "timeline",
                        "task_id": task.task_id,
                        "kind": "coverage",
                        "label": "覆盖率评估",
                        "detail": f"已入库 {len(accepted)} 份材料",
                    },
                )
                coverage = await self._run_agent(
                    self.roles["coverage"],
                    f"研究问题:\n{questions}\n\n{evidence_block}\n\n"
                    "逐问题评估证据是否充分。",
                    task.task_id,
                )
                await self._emit(
                    sink,
                    {
                        "event": "timeline",
                        "task_id": task.task_id,
                        "kind": "evidence",
                        "label": "证据核验",
                        "detail": "识别支持与矛盾证据",
                    },
                )
                evidence = await self._run_agent(
                    self.roles["verifier"],
                    f"研究问题:\n{questions}\n\n{evidence_block}\n\n"
                    "对关键主张核验证据并识别冲突。",
                    task.task_id,
                )
                decision = await self._run_agent(
                    self.roles["decider"],
                    f"覆盖评估:\n{coverage.summary}\n\n"
                    f"证据核验:\n{evidence.summary}\n\n"
                    f"{evidence_block}\n\n"
                    "决定下一步：继续搜索或结束。",
                    task.task_id,
                )
                if decision.action == "finish":
                    if not context.citations:
                        decision = ResearchDecision(
                            action="search",
                            directions=[
                                SearchDirection(
                                    query=SearchQuery(text=task.question)
                                )
                            ],
                            evidence_gaps=["no evidence collected"],
                            reason="must search before finishing",
                        )
                        directions = decision.directions
                        continue
                    citations = self._resolve_citations(
                        decision.citation_ids, context
                    )
                    if not citations and context.citations:
                        citations = list(context.citations)
                    await self._emit(
                        sink,
                        {
                            "event": "timeline",
                            "task_id": task.task_id,
                            "kind": "report",
                            "label": "撰写研究报告",
                            "detail": "整理证据并生成结构化报告",
                        },
                    )
                    report = await self._run_agent(
                        self.roles["writer"],
                        f"研究主题:\n{task.question}\n\n"
                        f"研究问题:\n{questions}\n\n"
                        f"覆盖评估:\n{coverage.summary}\n\n"
                        f"证据核验:\n{evidence.summary}\n\n"
                        f"{evidence_block}\n\n"
                        "撰写结构化研究报告。",
                        task.task_id,
                    )
                    writer_citations = self._resolve_citations(
                        report.citation_ids, context
                    )
                    if writer_citations:
                        citations = writer_citations
                    answer = report.markdown()
                    result = ResearchResult(
                        task_id=task.task_id,
                        status="completed",
                        answer=answer,
                        citations=citations,
                        stop_reason="evidence_sufficient",
                        usage=self.store.get_task(task.task_id).budget_used,
                        report=report,
                    )
                    await self._emit_answer(sink, task.task_id, result.answer)
                    await self._emit(
                        sink,
                        {
                            "event": "timeline",
                            "task_id": task.task_id,
                            "kind": "decision",
                            "label": "提交研究结果",
                            "detail": "已提交检查点",
                        },
                    )
                    await self._emit(
                        sink,
                        {
                            "event": "run.status",
                            "task_id": task.task_id,
                            "status": "succeeded",
                        },
                    )
                    await self._emit(
                        sink,
                        {
                            "event": "run.phase",
                            "task_id": task.task_id,
                            "phase": "checkpointing",
                        },
                    )
                    self._save_checkpoint(task, round_no, accepted, result)
                    return result
                directions = decision.directions
                last_summary = (
                    f"覆盖评估: {coverage.summary}\n"
                    f"证据核验: {evidence.summary}"
                )
                self._save_checkpoint(task, round_no, accepted, None)
            result = ResearchResult(
                task_id=task.task_id,
                status="partial",
                answer=last_summary,
                stop_reason="max_rounds",
                limitations=["max rounds reached", "no conclusive finish"],
                usage=self.store.get_task(task.task_id).budget_used,
            )
            await self._emit(
                sink,
                {
                    "event": "run.status",
                    "task_id": task.task_id,
                    "status": "failed",
                },
            )
            self._save_checkpoint(task, round_no, accepted, result)
            return result
        finally:
            lock.release()

    async def _emit_answer(
        self, sink: EventSink | None, task_id: str, answer: str
    ) -> None:
        await self._emit(sink, {"event": "answer.started", "task_id": task_id})
        for i in range(0, len(answer), 64):
            await self._emit(
                sink,
                {
                    "event": "answer.delta",
                    "task_id": task_id,
                    "delta": answer[i : i + 64],
                },
            )
        await self._emit(
            sink, {"event": "answer.completed", "task_id": task_id}
        )

    @staticmethod
    def _resolve_citations(ids: list[str], context: ContextPackage):
        by_id = {c.citation_id: c for c in context.citations}
        return [by_id[cid] for cid in ids if cid in by_id]

    def _save_checkpoint(self, task, round_no, accepted, result) -> None:
        usage = self.store.get_task(task.task_id).budget_used
        checkpoint = Checkpoint(
            task_id=task.task_id,
            round=round_no,
            accepted_artifact_ids=accepted,
            budget_used=usage,
            stop_reason=result.stop_reason if result else None,
            updated_at=datetime.now(UTC),
        )
        self.store.save_checkpoint(task.task_id, checkpoint, usage)
