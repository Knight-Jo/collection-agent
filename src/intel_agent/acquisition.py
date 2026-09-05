"""AcquisitionPipeline: FETCH → EXTRACT → NORMALIZE → STORE per item."""

from __future__ import annotations

from .contracts.documents import NormalizationInput
from .contracts.errors import DomainError
from .contracts.research import SearchHit
from .contracts.resources import FetchRequest, Resource
from .indexing.models import AcquisitionReport
from .indexing.service import IndexingService
from .normalization import Normalizer
from .storage.materials import MaterialStore

STAGES = ("fetch", "extract", "normalize", "store", "index")
type Source = SearchHit | Resource


class AcquisitionPipeline:
    def __init__(
        self,
        fetch_service,
        extraction_service,
        normalizer: Normalizer,
        store: MaterialStore,
        resource_store,
        indexing_service: IndexingService | None = None,
    ) -> None:
        self.fetch_service = fetch_service
        self.extraction_service = extraction_service
        self.normalizer = normalizer
        self.store = store
        self.resource_store = resource_store
        self.indexing_service = indexing_service

    async def acquire(
        self,
        task_id: str,
        source: Source,
        profile_id: str,
        *,
        index_after_store: bool = False,
    ) -> AcquisitionReport:
        if isinstance(source, Resource):
            resource = source
            work_item_id = self.store.create_work_item(
                task_id,
                "",
                profile_id,
                index_after_store,
                resource_id=resource.resource_id,
            )
            self.store.update_work_item(
                work_item_id, "fetch", "done", resource_id=resource.resource_id
            )
        else:
            work_item_id = self.store.create_work_item(
                task_id, source.url, profile_id, index_after_store
            )
        return await self._run(
            task_id, work_item_id, source, profile_id, index_after_store
        )

    async def resume_item(self, work_item_id: str) -> AcquisitionReport:
        item = self.store.get_work_item(work_item_id)
        payload = item["payload"]
        source: Source
        if item["resource_id"]:
            source = self.store.get_resource(item["resource_id"])
        else:
            source = SearchHit(
                hit_id="",
                url=payload["source_url"],
                dedup_key=payload["source_url"],
                source_types=["web"],
            )
        return await self._run(
            item["task_id"],
            work_item_id,
            source,
            payload["profile_id"],
            payload["index_after_store"],
        )

    async def _run(
        self, task_id, work_item_id, source, profile_id, index_after_store
    ) -> AcquisitionReport:
        item = self.store.get_work_item(work_item_id)
        resource_id = item.get("resource_id")
        artifact_id = item.get("artifact_id")

        # Already stored: only indexing can remain.
        if artifact_id is not None:
            if index_after_store and self.indexing_service is not None:
                await self.indexing_service.index(artifact_id)
                self.store.update_work_item(work_item_id, "index", "done")
            return AcquisitionReport(
                task_id=task_id,
                work_item_id=work_item_id,
                artifact_id=artifact_id,
                stage="done",
                status="success",
            )

        # FETCH
        if resource_id is None:
            if isinstance(source, Resource):
                resource = source
            else:
                try:
                    fetch_result = await self.fetch_service.fetch(
                        FetchRequest(url=source.url)
                    )
                    resource = fetch_result.resource
                except DomainError as error:
                    self.store.update_work_item(
                        work_item_id, "fetch", "failed"
                    )
                    return AcquisitionReport(
                        task_id=task_id,
                        work_item_id=work_item_id,
                        stage="fetch",
                        status="failed",
                        error=error.code,
                    )
            resource_id = resource.resource_id
            self.store.update_work_item(
                work_item_id, "fetch", "done", resource_id=resource_id
            )
        else:
            resource = self.store.get_resource(resource_id)

        # EXTRACT
        try:
            pid = (
                self.extraction_service.profile_for(resource.media_type)
                or profile_id
            )
            extract_result = await self.extraction_service.extract(
                resource, pid
            )
        except DomainError as error:
            self.store.update_work_item(work_item_id, "extract", "failed")
            return AcquisitionReport(
                task_id=task_id,
                work_item_id=work_item_id,
                stage="extract",
                status="failed",
                error=error.code,
            )
        self.store.update_work_item(work_item_id, "extract", "done")

        # NORMALIZE + STORE (idempotent)
        if artifact_id is None:
            source_key = self._source_key(source, resource)
            identity = self.store.resolve_identity(source_key)
            revision = self.store.resolve_revision(
                identity.document_id, resource_id
            )
            input_ = NormalizationInput(
                result=extract_result,
                resource_id=resource_id,
                identity=identity,
                revision_id=revision,
                provenance=self._provenance(source),
            )
            document = self.normalizer.normalize(input_)
            artifact_id = self.store.save_document(task_id, document)
            self.store.update_work_item(
                work_item_id, "store", "done", artifact_id=artifact_id
            )

        # INDEX
        if index_after_store and self.indexing_service is not None:
            await self.indexing_service.index(artifact_id)
            self.store.update_work_item(work_item_id, "index", "done")

        return AcquisitionReport(
            task_id=task_id,
            work_item_id=work_item_id,
            artifact_id=artifact_id,
            stage="done",
            status="success",
        )

    @staticmethod
    def _source_key(source: Source, resource: Resource) -> str:
        if isinstance(source, SearchHit):
            return source.url
        return (
            resource.origin.final_url
            or resource.origin.local_display_name
            or resource.content_hash
        )

    @staticmethod
    def _provenance(source: Source):
        if isinstance(source, SearchHit):
            return source.occurrences
        return []
