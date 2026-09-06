"""Media fact-extraction tests (spec 002 US4 / T403)."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from intel_agent.contracts.documents import Locator
from intel_agent.media.models import (
    FactExtractionItem,
    FactExtractionResult,
    MediaJob,
    MediaSegment,
)
from intel_agent.media.service import MediaService
from intel_agent.storage.media import MediaStore
from intel_agent.storage.sqlite import SqliteStore
from intel_agent.storage.tasks import TaskStore


class _Usage:
    requests = 1
    input_tokens = 100
    output_tokens = 50


class _AgentResult:
    def __init__(self, output):
        self.output = output
        self.usage = _Usage()


class _FakeExtractor:
    """Mimics the pydantic-ai fact_extractor agent."""

    def __init__(self, result):
        self._result = result
        self.prompt: str | None = None

    async def run(self, prompt):
        self.prompt = prompt
        return _AgentResult(self._result)


class _FakeApp:
    def register_runner(self, kind, runner):
        pass


class _TestService(MediaService):
    def __init__(self, *args, segments_fn):
        super().__init__(*args)
        self._segments_fn = segments_fn

    def segments(self, media_job_id: str) -> list[MediaSegment]:
        return self._segments_fn(media_job_id)


class _Harness:
    def __init__(self, result: FactExtractionResult):
        self.dir = Path(tempfile.mkdtemp())
        sqlite = SqliteStore(self.dir / "media.sqlite")
        self.store = MediaStore(sqlite)
        self.task_store = TaskStore(sqlite)
        self.extractor = _FakeExtractor(result)
        self.app = _FakeApp()
        self.service = _TestService(
            self.store,
            self.task_store,
            None,
            None,
            self.app,
            None,
            {"fact_extractor": self.extractor},
            segments_fn=lambda media_job_id: self.transcript(media_job_id),
        )

    def new_job(self) -> MediaJob:
        task = self.task_store.create_task("media", kind="media")
        return MediaJob(
            media_job_id="mj1",
            task_id=task.task_id,
            resource_id="r1",
            filename="a.mp3",
            kind="audio",
            media_type="audio/mpeg",
            size_bytes=100,
            summary=None,
        )

    def transcript(self, media_job_id: str) -> list[MediaSegment]:
        return [
            MediaSegment(
                segment_id=f"s{media_job_id}-1",
                media_job_id=media_job_id,
                artifact_id="art1",
                block_id="b1",
                locator=Locator(start_ms=0, end_ms=5000),
                text="锂离子电池正极材料需要回收。",
            ),
            MediaSegment(
                segment_id=f"s{media_job_id}-2",
                media_job_id=media_job_id,
                artifact_id="art1",
                block_id="b2",
                locator=Locator(start_ms=5000, end_ms=10000),
                text="湿法冶金是主流工艺。",
            ),
            MediaSegment(
                segment_id=f"s{media_job_id}-3",
                media_job_id=media_job_id,
                artifact_id="art1",
                block_id="b3",
                locator=Locator(start_ms=10000, end_ms=15000),
                text="直接回收法还在产业化早期。",
            ),
        ]


def test_extracts_semantic_facts_with_summary_and_budget():
    h = _Harness(
        FactExtractionResult(
            summary="讨论了几种锂电池回收工艺。",
            facts=[
                FactExtractionItem(
                    statement=("锂电池回收存在湿法冶金与直接回收两种主要工艺"),
                    segment_indices=[2, 3],
                )
            ],
        )
    )
    job = h.new_job()

    asyncio.run(h.service._extract_facts(job))

    facts = h.store.list_facts(job.media_job_id)
    assert len(facts) == 1
    assert facts[0].verification_status == "unverified"
    assert len(facts[0].segment_ids) == 2  # multi-segment association

    evidence = h.store.list_evidence(job.media_job_id)
    assert len(evidence) == 2  # one evidence per supporting segment
    for ev in evidence:
        assert ev.fact_id == facts[0].fact_id
        assert ev.relation == "mentions"
        assert ev.quote
        assert ev.locator.start_ms is not None
        assert ev.locator.end_ms is not None

    # summary persisted on the job
    assert (
        h.store.get_job(job.media_job_id).summary
        == "讨论了几种锂电池回收工艺。"
    )

    # budget recorded on the task
    task = h.task_store.get_task(job.task_id)
    assert task.budget_used.llm_calls == 1
    assert h.extractor.prompt is not None
    assert "湿法冶金是主流工艺" in h.extractor.prompt


def test_drops_invalid_segment_indices():
    h = _Harness(
        FactExtractionResult(
            summary="s",
            facts=[
                FactExtractionItem(
                    statement="只有不存在的分段", segment_indices=[99]
                ),
                FactExtractionItem(
                    statement="跨越有效分段", segment_indices=[1, 3]
                ),
            ],
        )
    )
    job = h.new_job()

    asyncio.run(h.service._extract_facts(job))

    facts = h.store.list_facts(job.media_job_id)
    assert len(facts) == 1  # only the valid fact persisted
    assert facts[0].statement == "跨越有效分段"
    assert len(h.store.list_evidence(job.media_job_id)) == 2


def test_no_segments_skips_extraction():
    h = _Harness(FactExtractionResult())
    h.service._segments_fn = lambda media_job_id: []
    job = h.new_job()

    asyncio.run(h.service._extract_facts(job))

    assert h.store.list_facts(job.media_job_id) == []
    assert h.extractor.prompt is None
