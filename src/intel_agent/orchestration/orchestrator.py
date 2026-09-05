"""ResearchOrchestrator: deterministic research loop (spec §12)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path

from ..contracts.research import (
    Checkpoint,
    ContextPackage,
    ContextRequest,
    ResearchDecision,
    ResearchResult,
    ResearchTask,
    SearchQuery,
    SearchRequest,
)
from ..runtime.config import ResearchConfig
from ..storage.materials import MaterialStore
from .state import TaskLock

EventSink = Callable[[dict], Awaitable[None]]


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
        search_per_provider_limit: int = 10,
        search_total_limit: int = 20,
        event_sink: EventSink | None = None,
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
        self.search_per_provider_limit = search_per_provider_limit
        self.search_total_limit = search_total_limit
        self.event_sink = event_sink

    async def _emit(self, sink: EventSink | None, event: dict) -> None:
        if sink is not None:
            await sink(event)

    async def run(self, question: str) -> ResearchResult:
        task = self.store.create_task(
            question, deadline_seconds=self.config.deadline_seconds
        )
        return await self.run_task(task)

    async def resume(self, task_id: str) -> ResearchResult:
        task = self.store.get_task(task_id)
        return await self.run_task(task)

    async def run_task(
        self, task: ResearchTask, event_sink: EventSink | None = None
    ) -> ResearchResult:
        sink = event_sink or self.event_sink
        lock = TaskLock(self.lock_dir, task.task_id)
        lock.acquire()
        try:
            self.store.get_task(task.task_id)
            context = ContextPackage(
                task_id=task.task_id,
                query=task.question,
                scope_id="",
            )
            accepted: list[str] = []
            round_no = task.round
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
            for _ in range(self.config.max_rounds):
                decision = await self.agent.decide_with_repair(task, context)
                if decision.action == "finish" and not context.citations:
                    decision = ResearchDecision(
                        action="search",
                        queries=[SearchQuery(text=task.question)],
                        source_types=["web"],
                        evidence_gaps=["no evidence collected"],
                        reason="must search before finishing",
                    )
                if decision.action == "finish":
                    citations = self._resolve_citations(
                        decision.citation_ids, context
                    )
                    if not citations and context.citations:
                        citations = list(context.citations)
                    result = ResearchResult(
                        task_id=task.task_id,
                        status="completed",
                        answer=decision.draft_answer or "",
                        citations=citations,
                        stop_reason="evidence_sufficient",
                        usage=self.store.get_task(task.task_id).budget_used,
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
                await self._emit(
                    sink,
                    {
                        "event": "timeline",
                        "task_id": task.task_id,
                        "kind": "search_plan",
                        "label": "生成检索计划",
                        "detail": f"规划 {len(decision.queries)} 组检索方向",
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
                for query in decision.queries:
                    batch = await self.search_service.search(
                        SearchRequest(
                            query=query,
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
                        report = await self.acquisition_pipeline.acquire(
                            task.task_id, hit, self.profile_id
                        )
                        if report.artifact_id:
                            accepted.append(report.artifact_id)
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
                                # A single artifact's index failure must not
                                # abort the whole round.
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
                self._save_checkpoint(task, round_no, accepted, None)
            result = ResearchResult(
                task_id=task.task_id,
                status="partial",
                answer="",
                stop_reason="max_rounds",
                limitations=["max rounds reached"],
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
