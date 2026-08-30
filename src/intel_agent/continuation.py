"""Restricted continuation of an existing local research task."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic_ai import CancellationToken
from pydantic_ai.exceptions import RunCancelled
from pydantic_ai.usage import UsageLimits

from .agent import build_agent, build_deps
from .config import Settings
from .models import (
    ActionRequest,
    AssetRevisionRef,
    CollectionState,
    CommittedAssetType,
    ResearchBrief,
    ResearchRun,
)
from .runner import TaskRunSpec, run_agent_task
from .state_store import StateStore
from .task import activate_task, load_task, save_task
from .web.views import get_task_view

ALLOWED_CONTINUATION_TOOLS = {
    "web_search",
    "github_search",
    "academic_search",
    "news_search",
    "crawl_collect",
    "web_fetch",
    "document_search",
    "document_read",
    "fact_save",
    "fact_supersede",
    "evidence_save",
    "evidence_audit",
    "evidence_conflict_create",
    "evidence_conflict_resolve",
    "coverage_eval",
}

CONTINUATION_PROMPT = """\
你正在续研一个已经存在的公开信息调研任务。只能围绕用户给定范围补充搜索、抓取、
事实、证据、审核、冲突与覆盖评估。不得创建新任务，不得生成或修改报告，不得更改
任务主题和关键问题。完成这一轮明确范围后立即停止，并简述新增材料与仍存缺口。
"""


class ResearchGate:
    """Allow one research execution in the single-user workspace."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._owner: str | None = None

    @property
    def locked(self) -> bool:
        return self._lock.locked()

    async def acquire(self, owner: str) -> None:
        await self._lock.acquire()
        self._owner = owner

    async def try_acquire(self, owner: str) -> bool:
        if self._lock.locked():
            return False
        await self.acquire(owner)
        return True

    def release(self, owner: str) -> None:
        if self._owner != owner:
            raise RuntimeError("research gate owner mismatch")
        self._owner = None
        self._lock.release()


class ContinuationRunner:
    """Run one explicitly requested continuation and commit its asset delta."""

    def __init__(
        self,
        cwd: Path,
        settings: Settings | None = None,
        *,
        store: StateStore | None = None,
        gate: ResearchGate | None = None,
    ) -> None:
        self.cwd = cwd
        self.settings = settings or Settings()
        self.store = store or StateStore(cwd)
        self.gate = gate or ResearchGate()

    async def run_initial(
        self,
        run: ResearchRun,
        brief: ResearchBrief,
        cancellation_token: CancellationToken | None = None,
    ) -> ResearchRun:
        """Execute the queued initial run created by intake."""
        token = cancellation_token or CancellationToken()
        if token.cancelled:
            current = self.store.get_run(run.id)
            return (
                self.store.cancel_run(run.id)
                if current.status == "queued"
                else current
            )
        await self.gate.acquire(run.id)
        try:
            if token.cancelled:
                current = self.store.get_run(run.id)
                return (
                    self.store.cancel_run(run.id)
                    if current.status == "queued"
                    else current
                )
            self.store.claim_run(
                run.id,
                phase="planning",
                lease_owner=run.id,
                lease_expires_at=(
                    datetime.now(UTC) + timedelta(minutes=2)
                ).isoformat(),
            )
            self.store.create_search_plan_version(
                run.id,
                {
                    "topic": brief.topic,
                    "objective": brief.objective,
                    "questions": brief.key_questions,
                    "scope": brief.scope.model_dump(mode="json"),
                },
                trigger_message_id=run.trigger_message_id,
            )
            task = activate_task(self.cwd, run.task_id)
            before = _asset_snapshot(self.cwd, task.id)
            await run_agent_task(
                self.cwd,
                self.settings,
                TaskRunSpec(
                    topic=brief.topic,
                    objective=brief.objective,
                    questions=brief.key_questions,
                    scope=brief.scope,
                    report_depth=task.report_depth,
                    criteria=task.criteria,
                    deep_crawl=task.deep_crawl,
                ),
                cancellation_token=token,
                bound_task_id=task.id,
                run_id=run.id,
            )
            if token.cancelled:
                raise asyncio.CancelledError
            added = _asset_snapshot(self.cwd, task.id) - before
            self.store.finish_run(
                run.id,
                expected_input_version=run.input_committed_state_version,
                staged_manifest=_asset_revisions(task.id, added),
                outcome="committed" if added else "no_progress",
            )
            return self.store.get_run(run.id)
        except (RunCancelled, asyncio.CancelledError):
            current = self.store.get_run(run.id)
            if current.status == "queued":
                return self.store.cancel_run(run.id)
            if current.status == "running":
                self.store.stop_run(run.id)
            return self.store.finish_stop(run.id)
        except Exception as error:
            current = self.store.get_run(run.id)
            if current.status == "running":
                return self.store.transition_run(
                    run.id, "failed", error=str(error)
                )
            return current
        finally:
            self.gate.release(run.id)

    async def run(
        self,
        action: ActionRequest,
        cancellation_token: CancellationToken | None = None,
    ) -> ActionRequest:
        """Execute one queued continuation and return its terminal action."""
        token = cancellation_token or CancellationToken()
        run = self.store.create_run(
            action.task_id,
            "continue_research",
            self.store.committed_state_version(action.task_id),
            {
                "action_type": action.action_type,
                "scope": action.immutable_payload,
            },
            trigger_message_id=action.trigger_message_id,
            action_request_id=action.id,
        )
        if token.cancelled:
            self.store.transition_run(run.id, "cancelled")
            return self.store.transition_action(action.id, "cancelled")

        await self.gate.acquire(run.id)
        saved_collection: CollectionState | None = None
        try:
            if token.cancelled:
                self.store.transition_run(run.id, "cancelled")
                return self.store.transition_action(action.id, "cancelled")
            self.store.transition_action(
                action.id, "executing", created_research_run_id=run.id
            )
            self.store.claim_run(
                run.id,
                phase="collecting",
                lease_owner=run.id,
                lease_expires_at=(
                    datetime.now(UTC) + timedelta(minutes=2)
                ).isoformat(),
            )
            self.store.create_search_plan_version(
                run.id,
                {
                    "action_type": action.action_type,
                    "scope": action.immutable_payload,
                },
                trigger_message_id=action.trigger_message_id,
                action_request_id=action.id,
            )
            task = activate_task(self.cwd, action.task_id)
            saved_collection = task.collection
            save_task(
                self.cwd,
                task.model_copy(
                    update={
                        "collection": task.collection.model_copy(
                            update={
                                "search_attempts": 0,
                                "search_stop_reason": None,
                                "fetch_attempts_since_evidence": 0,
                                "stop_reason": None,
                            }
                        )
                    }
                ),
            )
            before = _asset_snapshot(self.cwd, action.task_id)
            agent = build_agent(
                self.settings,
                system_prompt=CONTINUATION_PROMPT,
                allowed_tools=ALLOWED_CONTINUATION_TOOLS,
            )
            deps = build_deps(
                self.cwd,
                self.settings,
                deep_crawl=task.deep_crawl,
                task_id=action.task_id,
                run_id=run.id,
            )
            prompt = (
                "继续当前任务，严格限定在以下用户请求范围：\n"
                + json.dumps(action.immutable_payload, ensure_ascii=False)
            )
            await agent.run(
                prompt,
                deps=deps,
                usage_limits=UsageLimits(
                    request_limit=self.settings.budgets.request_limit
                ),
                cancellation_token=token,
            )
            if token.cancelled:
                raise asyncio.CancelledError
            after = _asset_snapshot(self.cwd, action.task_id)
            added = after - before
            self.store.finish_run(
                run.id,
                expected_input_version=run.input_committed_state_version,
                staged_manifest=_asset_revisions(action.task_id, added),
                outcome="committed" if added else "no_progress",
            )
            return self.store.get_action(action.id)
        except (RunCancelled, asyncio.CancelledError):
            current_run = self.store.get_run(run.id)
            if current_run.status == "running":
                self.store.stop_run(run.id)
                self.store.finish_stop(run.id)
            elif current_run.status == "stopping":
                self.store.finish_stop(run.id)
            current_action = self.store.get_action(action.id)
            if current_action.status == "executing":
                return self.store.transition_action(action.id, "cancelled")
            return current_action
        except Exception as error:
            current_run = self.store.get_run(run.id)
            if current_run.status == "running":
                self.store.transition_run(run.id, "failed", error=str(error))
            current_action = self.store.get_action(action.id)
            if current_action.status == "executing":
                return self.store.transition_action(
                    action.id, "failed", error=str(error)
                )
            return current_action
        finally:
            if saved_collection is not None:
                latest = load_task(self.cwd, action.task_id)
                restored = saved_collection.model_copy(
                    update={"evidence_count": latest.collection.evidence_count}
                )
                save_task(
                    self.cwd,
                    latest.model_copy(update={"collection": restored}),
                )
            self.gate.release(run.id)


def _asset_snapshot(
    cwd: Path, task_id: str
) -> set[tuple[CommittedAssetType, str]]:
    view = get_task_view(cwd, task_id)
    assets: set[tuple[CommittedAssetType, str]] = {
        ("document", resource.document_id)
        for resource in view.resources
        if resource.document_id is not None
    }
    for question in view.questions:
        for fact in question.facts:
            assets.add(("fact", fact.id))
            for evidence in fact.evidence:
                assets.add(("evidence", evidence.id))
                assets.add(("document", evidence.document.id))
    return assets


def _asset_revisions(
    task_id: str,
    assets: set[tuple[CommittedAssetType, str]],
) -> list[AssetRevisionRef]:
    """Convert the JSON task delta into stable references for the run workspace."""
    return [
        AssetRevisionRef(
            asset_type=asset_type,
            logical_id=asset_id,
            revision_id=asset_id,
            content_sha256="",
            task_id=task_id,
        )
        for asset_type, asset_id in sorted(assets)
    ]
