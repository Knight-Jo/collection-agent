"""Media analysis application service (spec 002 US4)."""

from __future__ import annotations

import logging

from ..contracts.documents import BlockSpan, Locator
from ..contracts.research import BudgetUsage
from ..storage._ids import new_id
from ..storage.media import MediaStore
from ..storage.tasks import TaskStore
from .models import (
    MediaEvidence,
    MediaFact,
    MediaJob,
    MediaJobView,
    MediaSegment,
)

logger = logging.getLogger("intel_agent.media")


class MediaService:
    def __init__(
        self,
        store: MediaStore,
        task_store: TaskStore,
        material_store,
        acquisition_pipeline,
        application,
        settings,
        roles=None,
    ) -> None:
        self.store = store
        self.task_store = task_store
        self.material_store = material_store
        self.acquisition = acquisition_pipeline
        self.application = application
        self.settings = settings
        self.roles = roles or {}
        self.application.register_runner("media", self._run)

    def submit(
        self,
        resource_id: str,
        filename: str,
        kind: str,
        media_type: str,
        size_bytes: int,
    ) -> MediaJob:
        task = self.task_store.create_task(
            filename,
            kind="media",
            deadline_seconds=self.settings.research.deadline_seconds,
        )
        job = MediaJob(
            media_job_id=new_id("media"),
            task_id=task.task_id,
            resource_id=resource_id,
            filename=filename,
            kind=kind,  # type: ignore[arg-type]
            media_type=media_type,
            size_bytes=size_bytes,
            input_snapshot={},
        )
        self.store.save_job(job)
        self.task_store.add_timeline(task.task_id, "queued", "submitted")
        logger.info(
            "media job submitted id=%s filename=%s kind=%s",
            job.media_job_id,
            filename,
            kind,
        )
        self.application.launch(task.task_id, self._run)
        return job

    def list(self) -> list[MediaJob]:
        return self.store.list()

    def get(self, media_job_id: str) -> MediaJobView:
        job = self.store.get_job(media_job_id)
        task = self.task_store.get_task(job.task_id)
        return MediaJobView(
            job=job,
            status=task.status,
            phase=task.phase,
            error=task.error,
            segments=self.segments(media_job_id),
            facts=self.store.list_facts(media_job_id),
            evidence=self.store.list_evidence(media_job_id),
        )

    def segments(self, media_job_id: str) -> list[MediaSegment]:
        job = self.store.get_job(media_job_id)
        if job.artifact_id is None:
            return []
        document = self.material_store.get_document(job.artifact_id)
        out: list[MediaSegment] = []
        for block in document.blocks:
            if block.locator.start_ms is None or block.locator.end_ms is None:
                continue
            out.append(
                MediaSegment(
                    segment_id=f"{job.media_job_id}:{job.artifact_id}:{block.block_id}",
                    media_job_id=media_job_id,
                    artifact_id=job.artifact_id,
                    block_id=block.block_id,
                    locator=block.locator,
                    text=block.text,
                    speaker=None,
                    confidence=None,
                )
            )
        return out

    async def _run(self, task_id: str) -> None:
        job = self.store.get_by_task(task_id)
        if job is None:
            return
        logger.info("media job started id=%s", job.media_job_id)
        self.task_store.claim_queued(task_id)
        self.task_store.set_phase(task_id, "transcribing")
        self.task_store.add_timeline(task_id, "transcribing", "started")

        resource = self.material_store.get_resource(job.resource_id)
        profile = self._profile_for(job.media_type)
        report = await self.acquisition.acquire(
            task_id, resource, profile, index_after_store=False
        )
        if not report.artifact_id:
            logger.warning(
                "media job failed id=%s stage=%s error=%s",
                job.media_job_id,
                report.stage,
                report.error,
            )
            self.task_store.update_task_status(
                task_id,
                "failed",
                phase="transcribing",
                error={
                    "code": "EXTRACTION_FAILED",
                    "message": report.error or "no artifact produced",
                    "stage": "media",
                    "retryable": True,
                },
            )
            return

        job.artifact_id = report.artifact_id
        self.store.save_job(job)

        self.task_store.set_phase(task_id, "analyzing")
        await self._extract_facts(job)

        facts = self.store.list_facts(job.media_job_id)
        segments = self.segments(job.media_job_id)
        logger.info(
            "media job completed id=%s segments=%d facts=%d",
            job.media_job_id,
            len(segments),
            len(facts),
        )
        self.task_store.update_task_status(task_id, "completed", phase="done")
        self.task_store.add_timeline(task_id, "done", "completed")

    def _profile_for(self, media_type: str) -> str:
        return "audio" if media_type.startswith("audio/") else "video"

    async def _extract_facts(self, job: MediaJob) -> None:
        """Extract semantic facts from the transcript via the agent role.

        The fact-extractor agent reads the full segmented transcript and
        returns a summary plus independent statements, each referencing the
        segment indices that support it. Facts stay ``unverified`` and their
        in-material source is recorded per segment with ``relation=mentions``.
        """
        segments = self.segments(job.media_job_id)
        if not segments:
            return
        extractor = self.roles.get("fact_extractor")
        if extractor is None:
            logger.warning(
                "media job %s: fact_extractor role unavailable; "
                "skipping extraction",
                job.media_job_id,
            )
            return

        # One-based indices referenced by the agent, mapped back to segments.
        transcript = "\n".join(
            f"[{i}] {self._format_time(s)} {s.text}"
            for i, s in enumerate(segments, start=1)
        )
        prompt = (
            f"请阅读以下语音转写分段，抽取可独立核验的声明并给出简短摘要。\n\n"
            f"{transcript}"
        )
        logger.debug(
            "media job %s: extracting facts from %d segments",
            job.media_job_id,
            len(segments),
        )
        result = await extractor.run(prompt)
        usage = result.usage
        self.task_store.record_budget_change(
            job.task_id,
            BudgetUsage(
                llm_calls=usage.requests,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
            ),
        )

        by_index = {i: s for i, s in enumerate(segments, start=1)}
        output = result.output

        if output.summary:
            job.summary = output.summary
            self.store.save_job(job)

        for item in output.facts:
            statement = (item.statement or "").strip()
            if not statement:
                continue
            refs = [by_index[i] for i in item.segment_indices if i in by_index]
            if not refs:
                continue
            fact = MediaFact(
                fact_id=new_id("mf"),
                media_job_id=job.media_job_id,
                statement=statement,
                segment_ids=[s.segment_id for s in refs],
                verification_status="unverified",
            )
            self.store.save_fact(fact)
            for segment in refs:
                self._save_mention_evidence(job, fact, segment)

    def _save_mention_evidence(
        self, job: MediaJob, fact: MediaFact, segment: MediaSegment
    ) -> None:
        quote = segment.text.strip()
        self.store.save_evidence(
            MediaEvidence(
                evidence_id=new_id("me"),
                media_job_id=job.media_job_id,
                fact_id=fact.fact_id,
                segment_id=segment.segment_id,
                artifact_id=segment.artifact_id,
                block_span=BlockSpan(
                    block_id=segment.block_id,
                    char_start=0,
                    char_end=len(segment.text),
                ),
                locator=Locator(
                    start_ms=segment.locator.start_ms,
                    end_ms=segment.locator.end_ms,
                ),
                quote=quote,
                relation="mentions",
            )
        )

    @staticmethod
    def _format_time(segment: MediaSegment) -> str:
        start = segment.locator.start_ms or 0
        end = segment.locator.end_ms or 0

        def fmt(ms: int) -> str:
            total = ms // 1000
            return f"{total // 60:02d}:{total % 60:02d}"

        return f"{fmt(start)}-{fmt(end)}"
