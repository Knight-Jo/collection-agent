"""AcquisitionPipeline: FETCH → EXTRACT → NORMALIZE → STORE per item."""

from __future__ import annotations

import html as _html
import logging
from datetime import UTC, datetime

from .contracts.documents import NormalizationInput
from .contracts.errors import DomainError
from .contracts.research import SearchHit
from .contracts.resources import FetchRequest, Resource, ResourceOrigin
from .indexing.models import AcquisitionReport
from .indexing.service import IndexingService
from .normalization import Normalizer
from .storage.materials import MaterialStore

STAGES = ("fetch", "extract", "normalize", "store", "index")
type Source = SearchHit | Resource

logger = logging.getLogger("intel_agent.acquisition")


class AcquisitionPipeline:
    """Acquire a source and turn it into a stored, optionally indexed document.

    The pipeline runs the stages FETCH, EXTRACT, NORMALIZE, STORE, and INDEX.
    Each work item records its progress so interrupted items can be resumed
    without repeating completed stages.

    Attributes:
        fetch_service: Retrieves remote sources.
        extraction_service: Extracts structured content from resources.
        normalizer: Converts extracted content into a document model.
        store: Persists work items, identities, revisions, and documents.
        resource_store: Persists fetched resource content.
        indexing_service: Optionally indexes stored documents.
    """

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
        """Start acquisition for a search hit or an existing resource.

        Args:
            task_id: Identifier of the research task owning the work item.
            source: Search result or resource to process.
            profile_id: Fallback extraction profile.
            index_after_store: Whether to index the document after storing it.

        Returns:
            A report describing the completed or failed acquisition stage.
        """
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
        """Resume a previously created work item from its recorded progress.

        Args:
            work_item_id: Identifier of the work item to resume.

        Returns:
            A report describing the completed or failed acquisition stage.
        """
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

        # A stored artifact only needs the optional indexing stage.
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

        # Fetch or reuse the source resource.
        if resource_id is None:
            if isinstance(source, Resource):
                resource = source
            elif getattr(source, "content", None):
                resource = await self._content_resource(source)
            else:
                try:
                    timeout = getattr(
                        self.fetch_service, "default_timeout", 30.0
                    )
                    fetch_result = await self.fetch_service.fetch(
                        FetchRequest(url=source.url, timeout_seconds=timeout)
                    )
                    resource = fetch_result.resource
                except DomainError as error:
                    logger.warning(
                        "fetch failed task=%s error=%s", task_id, error.code
                    )
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
            logger.debug(
                "fetched task=%s resource=%s media_type=%s bytes=%d",
                task_id,
                resource_id,
                resource.media_type,
                resource.byte_length,
            )
            self.store.update_work_item(
                work_item_id, "fetch", "done", resource_id=resource_id
            )
        else:
            resource = self.store.get_resource(resource_id)

        # Extract content using the media-type-specific profile when available.
        try:
            pid = (
                self.extraction_service.profile_for(resource.media_type)
                or profile_id
            )
            extract_result = await self.extraction_service.extract(
                resource, pid
            )
        except DomainError as error:
            logger.warning(
                "extract failed task=%s error=%s", task_id, error.code
            )
            self.store.update_work_item(work_item_id, "extract", "failed")
            return AcquisitionReport(
                task_id=task_id,
                work_item_id=work_item_id,
                stage="extract",
                status="failed",
                error=error.code,
            )
        self.store.update_work_item(work_item_id, "extract", "done")

        # Normalize and store only when no artifact exists yet.
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
            logger.debug(
                "stored task=%s artifact=%s blocks=%d",
                task_id,
                artifact_id,
                len(document.blocks),
            )
            self.store.update_work_item(
                work_item_id, "store", "done", artifact_id=artifact_id
            )

        # Index the artifact when requested and an index is configured.
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

    async def _content_resource(self, source: SearchHit) -> Resource:
        """Store a provider-supplied text payload as an HTML resource."""
        title = source.title or ""
        body = _html.escape(source.content or "")
        doc = (
            "<html><head><meta charset='utf-8'><title>"
            f"{_html.escape(title)}</title></head><body>{body}</body></html>"
        )

        async def chunks():
            data = doc.encode("utf-8")
            for i in range(0, len(data), 64 * 1024):
                yield data[i : i + 64 * 1024]

        return await self.resource_store.write_stream(
            chunks(),
            origin=ResourceOrigin(
                requested_url=source.url,
                final_url=source.url,
                acquired_at=datetime.now(UTC),
            ),
            media_type="text/html",
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
