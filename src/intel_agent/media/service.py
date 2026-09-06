"""Media analysis application service (spec 002 US4)."""

from __future__ import annotations

import logging

from ..contracts.documents import BlockSpan, Locator
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
    ) -> None:
        self.store = store
        self.task_store = task_store
        self.material_store = material_store
        self.acquisition = acquisition_pipeline
        self.application = application
        self.settings = settings
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
        self._extract_facts(job)

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

    def _extract_facts(self, job: MediaJob) -> None:
        # Facts are extracted from transcript blocks. The verifier role is not
        # invoked here: media statements stay unverified (spec §5).
        for segment in self.segments(job.media_job_id):
            statement = segment.text.strip()
            if not statement:
                continue
            fact = MediaFact(
                fact_id=new_id("mf"),
                media_job_id=job.media_job_id,
                statement=statement,
                segment_ids=[segment.segment_id],
                verification_status="unverified",
            )
            self.store.save_fact(fact)
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
                    quote=statement,
                    relation="mentions",
                )
            )
