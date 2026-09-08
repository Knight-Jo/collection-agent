"""Monitor application service (spec 002 US1-US2)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from ..contracts.errors import DomainError
from ..storage._ids import new_id
from ..storage.monitoring import MonitoringStore
from ..storage.tasks import TaskStore
from .diff import (
    derive_fact_key,
    diff_baseline,
    normalize_source_key,
    normalize_statement,
)
from .models import (
    FactVersion,
    Monitor,
    MonitorChange,
    MonitorDetail,
    MonitorRun,
    MonitorRunView,
    MonitorSchedule,
)
from .scheduler import next_run_after

logger = logging.getLogger("intel_agent.monitoring")


class MonitoringService:
    def __init__(
        self,
        store: MonitoringStore,
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
        self.application.register_runner("monitor", self._run)

    # --- configuration ------------------------------------------------------

    def create_monitor(
        self,
        name: str,
        subject: str,
        strategy: str,
        schedule: MonitorSchedule,
        questions: list[str] | None = None,
        websites: list[str] | None = None,
    ) -> Monitor:
        now = datetime.now(UTC)
        monitor = Monitor(
            monitor_id=new_id("mon"),
            name=name,
            subject=subject,
            strategy=strategy,
            questions=questions or [],
            websites=websites or [],
            schedule=schedule,
            next_run_at=next_run_after(schedule, now),
            created_at=now,
            updated_at=now,
        )
        self.store.save_monitor(monitor)
        return monitor

    def update_monitor(self, monitor_id: str, patch: dict) -> Monitor:
        monitor = self.store.get_monitor(monitor_id)
        fields: dict = {}
        if "name" in patch:
            fields["name"] = patch["name"]
        if "subject" in patch:
            fields["subject"] = patch["subject"]
        if "strategy" in patch:
            fields["strategy"] = patch["strategy"]
        if "questions" in patch:
            fields["questions"] = patch["questions"]
        if "websites" in patch:
            fields["websites"] = patch["websites"]
        if "schedule" in patch:
            fields["schedule"] = patch["schedule"]
        if "status" in patch:
            fields["status"] = patch["status"]
            if patch["status"] == "paused":
                self.store.set_next_run(monitor_id, None)
        if fields:
            # Rebuild the full model from the merged patch so save_monitor
            # persists the new values; writing the pre-patch snapshot back
            # would silently undo the update.
            merged = monitor.model_dump(mode="json")
            merged.update(fields)
            merged["config_version"] = monitor.config_version + 1
            self.store.save_monitor(Monitor.model_validate(merged))
        return self.store.get_monitor(monitor_id)

    def toggle(self, monitor_id: str) -> Monitor:
        monitor = self.store.get_monitor(monitor_id)
        new_status = "paused" if monitor.status == "active" else "active"
        self.store.update_monitor_fields(monitor_id, {"status": new_status})
        if new_status == "paused":
            self.store.set_next_run(monitor_id, None)
        else:
            self.store.set_next_run(
                monitor_id, next_run_after(monitor.schedule, datetime.now(UTC))
            )
        return self.store.get_monitor(monitor_id)

    def list(self) -> list[Monitor]:
        return self.store.list_monitors()

    def get(self, monitor_id: str) -> MonitorDetail:
        monitor = self.store.get_monitor(monitor_id)
        runs = []
        for run in self.store.list_runs(monitor_id):
            task = self.task_store.get_task(run.task_id)
            runs.append(
                MonitorRunView(
                    run=run,
                    status=task.status,
                    phase=task.phase,
                    error=task.error,
                    changes=self.store.list_changes(run.run_id),
                )
            )
        return MonitorDetail(monitor=monitor, runs=runs)

    # --- run submission -----------------------------------------------------

    async def submit_run(self, monitor_id: str, trigger: str) -> MonitorRun:
        monitor = self.store.get_monitor(monitor_id)
        now = datetime.now(UTC)
        scheduled_for = now if trigger == "scheduled" else None
        if trigger == "manual":
            scheduled_for = None

        task = self.task_store.create_task(
            monitor.subject,
            kind="monitor",
            deadline_seconds=self.settings.research.deadline_seconds,
        )
        run = MonitorRun(
            run_id=new_id("monrun"),
            monitor_id=monitor_id,
            task_id=task.task_id,
            trigger=trigger,  # type: ignore[arg-type]
            scheduled_for=scheduled_for,
            input_snapshot={
                "config_version": monitor.config_version,
                "questions": monitor.questions,
                "websites": monitor.websites,
            },
            baseline_run_id=monitor.baseline_run_id,
            initial_baseline=monitor.baseline_run_id is None,
        )
        if not self.store.claim_active_run(monitor_id, run.run_id):
            raise DomainError(
                "CONFLICT",
                f"monitor already has an active run: {monitor_id}",
            )
        self.store.save_run(run)
        self.application.launch(run.task_id, self._run)
        return run

    # --- execution ----------------------------------------------------------

    async def _run(self, task_id: str) -> None:
        run = self.store.get_run_by_task(task_id)
        if run is None:
            return
        try:
            await self._execute(run, task_id)
        except Exception as error:
            # The active-run slot must be released even when the research
            # loop fails, or the monitor rejects every future run.
            logger.exception("monitor run failed run=%s", run.run_id)
            self._fail_run(run, error)

    def _fail_run(self, run: MonitorRun, error: Exception) -> None:
        code = getattr(error, "code", "MONITOR_RUN_FAILED")
        message = str(error) or error.__class__.__name__
        self.store.release_active_run(run.monitor_id, run.run_id)
        monitor = self.store.get_monitor(run.monitor_id)
        self.store.set_next_run(
            run.monitor_id, next_run_after(monitor.schedule, datetime.now(UTC))
        )
        self.task_store.update_task_status(
            run.task_id,
            "failed",
            phase="failed",
            error={"code": code, "message": message},
        )
        self.task_store.add_timeline(
            run.task_id, "failed", "monitor run failed"
        )

    async def _execute(self, run: MonitorRun, task_id: str) -> None:
        monitor = self.store.get_monitor(run.monitor_id)
        logger.info(
            "monitor run started run=%s monitor=%s", run.run_id, run.monitor_id
        )
        self.task_store.claim_queued(task_id)
        self.task_store.set_phase(task_id, "researching")
        self.task_store.add_timeline(task_id, "researching", "started")

        task = self.task_store.get_task(task_id)
        # Drive the research loop for the monitor's subject + questions.
        plan = await self._plan(monitor)
        assessment = await self.orchestrator.run_assessment(task, plan=plan)

        self.task_store.set_phase(task_id, "comparing")
        facts = self._facts_from_assessment(run, assessment)
        baseline = self._frozen_baseline(run, monitor)
        changes = self._compare(run, monitor, facts, baseline, assessment)
        logger.info(
            "monitor run compared run=%s facts=%d changes=%d",
            run.run_id,
            len(facts),
            len(changes),
        )

        self.store.save_run(
            MonitorRun(
                run_id=run.run_id,
                monitor_id=run.monitor_id,
                task_id=run.task_id,
                trigger=run.trigger,
                scheduled_for=run.scheduled_for,
                input_snapshot=run.input_snapshot,
                baseline_run_id=run.baseline_run_id,
                initial_baseline=run.initial_baseline,
                summary=f"{len(changes)} 项变化",
                limitations=assessment.limitations,
            )
        )
        self._commit(run, monitor, facts, changes, assessment)

    async def _plan(self, monitor: Monitor):
        prompt = f"调研主题: {monitor.subject}\n\n关注策略: {monitor.strategy}"
        result = await self.orchestrator.roles["planner"].run(prompt)
        return result.output

    def _facts_from_assessment(
        self, run: MonitorRun, assessment
    ) -> list[dict]:
        # Resolve claim citation ids to source URLs through the assessment's
        # fully-resolved citations; EvidenceItem itself carries no URL.
        citation_urls = {
            c.citation_id: (c.source_url or "") for c in assessment.citations
        }
        facts = []
        for item in assessment.evidence_review.claims:
            statement = item.claim.strip()
            if not statement:
                continue
            facts.append(
                {
                    # Key on the normalized statement so cosmetic rewording
                    # keeps identity; residual drift is handled by overlap
                    # matching in diff_baseline.
                    "fact_key": derive_fact_key(
                        normalize_statement(statement), "", {}
                    ),
                    "subject": statement,
                    "predicate": "",
                    "scope": {},
                    "value": {},
                    "statement": statement,
                    "citation_id": item.citation_id,
                    "source_title": item.source_title,
                    "source_url": citation_urls.get(item.citation_id, ""),
                }
            )
        return facts

    def _frozen_baseline(
        self, run: MonitorRun, monitor: Monitor
    ) -> dict[str, FactVersion]:
        if not run.baseline_run_id:
            return {}
        return self.store.baseline_facts(run.baseline_run_id)

    def _compare(
        self, run, monitor, facts, baseline: dict[str, FactVersion], assessment
    ) -> list[MonitorChange]:
        # The first run only freezes the baseline; reporting its every fact
        # as a change would flood the event feed.
        if not run.baseline_run_id:
            return []

        current = {f["fact_key"]: f["statement"] for f in facts}
        baseline_statements = {
            key: version.statement for key, version in baseline.items()
        }
        (
            new_keys,
            changed_keys,
            _matched,
            removed_keys,
            near_matches,
        ) = diff_baseline(current, baseline_statements)
        changes: list[MonitorChange] = []
        now = datetime.now(UTC)
        by_key = {f["fact_key"]: f for f in facts}

        for key in new_keys:
            f = by_key[key]
            changes.append(
                MonitorChange(
                    change_id=new_id("chg"),
                    run_id=run.run_id,
                    kind="new_fact",
                    current_version_id=f["fact_key"],
                    summary=f["statement"],
                    created_at=now,
                )
            )
        for key in changed_keys:
            f = by_key[key]
            previous = baseline[near_matches[key]]
            changes.append(
                MonitorChange(
                    change_id=new_id("chg"),
                    run_id=run.run_id,
                    kind="changed_fact",
                    previous_version_id=previous.fact_version_id,
                    current_version_id=f["fact_key"],
                    summary=f"{previous.statement} → {f['statement']}",
                    created_at=now,
                )
            )
        for key in removed_keys:
            previous = baseline[key]
            changes.append(
                MonitorChange(
                    change_id=new_id("chg"),
                    run_id=run.run_id,
                    kind="removed_fact",
                    previous_version_id=previous.fact_version_id,
                    summary=f"不再被来源支撑: {previous.statement}",
                    created_at=now,
                )
            )

        known_sources = self.store.baseline_source_keys(run.baseline_run_id)
        seen_sources = set()
        for f in facts:
            url = f.get("source_url") or ""
            if not url:
                continue
            key = normalize_source_key(url)
            if key and key not in known_sources and key not in seen_sources:
                seen_sources.add(key)
                changes.append(
                    MonitorChange(
                        change_id=new_id("chg"),
                        run_id=run.run_id,
                        kind="new_source",
                        source_key=key,
                        summary=f"新来源: {key}",
                        created_at=now,
                    )
                )
        return changes

    def _commit(self, run, monitor, facts, changes, assessment) -> None:
        citation_map = {c.citation_id: c for c in assessment.citations}
        for f in facts:
            citations = (
                [citation_map[f["citation_id"]]]
                if f["citation_id"] in citation_map
                else []
            )
            version = FactVersion(
                fact_version_id=f["fact_key"],
                monitor_id=run.monitor_id,
                created_run_id=run.run_id,
                fact_key=f["fact_key"],
                subject=f["subject"],
                predicate=f["predicate"],
                scope=f["scope"],
                value=f["value"],
                statement=f["statement"],
                citations=citations,
            )
            self.store.save_fact_version(version)
            self.store.save_baseline_fact(
                run.run_id, f["fact_key"], f["fact_key"]
            )
        for f in facts:
            url = f.get("source_url") or ""
            key = normalize_source_key(url)
            if key:
                self.store.save_baseline_source(run.run_id, key)
        for change in changes:
            self.store.save_change(change)

        if assessment.stop_reason == "evidence_sufficient":
            self.store.set_baseline(run.monitor_id, run.run_id)
        self.store.release_active_run(run.monitor_id, run.run_id)
        self.store.set_next_run(
            run.monitor_id,
            next_run_after(monitor.schedule, datetime.now(UTC)),
        )
        self.task_store.update_task_status(
            run.task_id,
            "completed",
            phase="done",
        )
        self.task_store.add_timeline(run.task_id, "done", "completed")
