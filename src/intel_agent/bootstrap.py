"""Unique assembly entry point (spec §3.1, §5)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx

from .acquisition import AcquisitionPipeline
from .agent.researcher import (
    OllamaLLMClient,
    OpenAILLMClient,
    ResearchAgent,
)
from .application import ResearchApplication
from .context.manager import ContextManager
from .context.retrieval import (
    HybridRetriever,
    LexicalRetriever,
    VectorRetriever,
)
from .conversation import ConversationService
from .extraction.backends.asr import WhisperBackend
from .extraction.backends.html import (
    BeautifulSoupBackend,
    TrafilaturaBackend,
)
from .extraction.backends.media import FFmpegBackend
from .extraction.backends.ocr import TesseractBackend
from .extraction.backends.office import OfficeBackend
from .extraction.backends.pdf import (
    PdfplumberBackend,
    PyMuPDFBackend,
)
from .extraction.registry import BackendRegistry
from .extraction.service import ExtractionService
from .fetch.browser import BrowserFetcher
from .fetch.service import FetchService
from .fetch.transport import build_client as build_fetch_client
from .indexing.embedding import HttpEmbeddingClient
from .indexing.qdrant import QdrantVectorIndex
from .indexing.service import IndexingService
from .indexing.tokenize import TiktokenCounter
from .normalization import Normalizer
from .orchestration.orchestrator import ResearchOrchestrator
from .runtime.config import ResearchSettings
from .runtime.events import EventBus
from .runtime.execution import Executor
from .search.providers import (
    ArxivProvider,
    OpenAlexProvider,
    RssProvider,
    SearXNGProvider,
)
from .search.service import SearchService
from .storage.materials import MaterialStore
from .storage.resources import ResourceStore


def build_search_providers(settings: ResearchSettings, client):
    providers = []
    cfg = settings.search.providers
    if cfg.get("searxng", None) is not None:
        p = cfg["searxng"]
        if p.enabled:
            providers.append(
                SearXNGProvider(client, p.base_url or "http://127.0.0.1:8888")
            )
    if cfg.get("arxiv", None) is not None and cfg["arxiv"].enabled:
        providers.append(ArxivProvider(client))
    if cfg.get("openalex", None) is not None and cfg["openalex"].enabled:
        providers.append(
            OpenAlexProvider(
                client,
                base_url=cfg["openalex"].base_url
                or "https://api.openalex.org/works",
            )
        )
    if cfg.get("rss", None) is not None and cfg["rss"].enabled:
        providers.append(
            RssProvider(client, feeds=cfg["rss"].extra.get("feeds", []))
        )
    return providers


def _build_llm_client(settings, client, counter):
    if settings.model.api_style == "ollama":
        return OllamaLLMClient(client, settings.model.model_id, counter)
    return OpenAILLMClient(
        client,
        settings.model.model_id,
        counter,
        disable_thinking=settings.model.disable_thinking,
    )


def _build_embedding(settings):
    if settings.embedding is None:
        return None, None, None
    client = httpx.AsyncClient(
        base_url=settings.embedding.base_url,
        trust_env=False,
        timeout=60.0,
    )
    if settings.embedding.api_key_env:
        import os

        key = os.environ.get(settings.embedding.api_key_env)
        if key:
            client.headers["Authorization"] = f"Bearer {key}"
    profile_id = settings.embedding.profile_id()
    embedding = HttpEmbeddingClient(
        client,
        settings.embedding.model_id,
        profile_id=profile_id,
        dimension=settings.embedding.dimension,
    )
    return embedding, client, profile_id


@asynccontextmanager
async def bootstrap(
    settings: ResearchSettings,
) -> AsyncIterator[ResearchApplication]:
    store = MaterialStore(settings.sqlite_file())
    resource_store = ResourceStore(
        settings.resources_root(),
        settings.import_roots() + [settings.tmp_root()],
        store,
    )
    executor = Executor(
        cpu_concurrency=settings.extraction.cpu_concurrency,
        gpu_concurrency=settings.extraction.gpu_concurrency,
    )

    registry = BackendRegistry()
    registry.register("trafilatura", TrafilaturaBackend(resource_store))
    registry.register("beautifulsoup", BeautifulSoupBackend(resource_store))
    registry.register("pymupdf", PyMuPDFBackend(resource_store))
    registry.register("pdfplumber", PdfplumberBackend(resource_store))
    registry.register(
        "tesseract",
        TesseractBackend(
            resource_store, executor, settings.extraction.ocr_languages
        ),
    )
    registry.register("office", OfficeBackend(resource_store))
    registry.register("ffmpeg", FFmpegBackend(resource_store, executor))
    registry.register(
        "whisper",
        WhisperBackend(
            resource_store,
            executor,
            model=settings.extraction.whisper_model,
            device=settings.extraction.whisper_device,
            compute_type=settings.extraction.whisper_compute_type,
            language=settings.extraction.whisper_language,
            device_index=settings.extraction.whisper_device_index,
        ),
    )

    extraction = ExtractionService(
        registry, resource_store, executor, settings.extraction
    )
    for profile in extraction.default_profiles():
        extraction.register_profile(profile)

    fetch_client = build_fetch_client(
        timeout=settings.fetch.http_timeout_seconds,
        proxy=settings.fetch.proxy_url,
    )
    search_client = httpx.AsyncClient(
        trust_env=False, timeout=settings.search.provider_timeout_seconds
    )
    llm_client = httpx.AsyncClient(
        base_url=settings.model.base_url,
        trust_env=False,
        timeout=120.0,
    )
    if settings.model.api_key_env:
        import os

        key = os.environ.get(settings.model.api_key_env)
        if key:
            llm_client.headers["Authorization"] = f"Bearer {key}"

    fetch_service = FetchService(
        fetch_client,
        resource_store,
        settings.fetch,
        BrowserFetcher(resource_store),
    )
    search_service = SearchService(
        build_search_providers(settings, search_client), settings.search
    )

    counter = TiktokenCounter()
    embedding_client, embedding_http, embedding_profile_id = _build_embedding(
        settings
    )
    vector_index = (
        QdrantVectorIndex(settings.storage.qdrant_url)
        if settings.storage.qdrant_url is not None
        else None
    )
    vector_retriever = None
    if (
        embedding_client is not None
        and vector_index is not None
        and embedding_profile_id is not None
    ):
        vector_retriever = VectorRetriever(
            store, embedding_client, vector_index
        )
    indexing = IndexingService(
        store,
        settings.indexing,
        counter,
        embedding_client=embedding_client,
        vector_index=vector_index,
        embedding_profile_id=embedding_profile_id,
    )
    context_manager = ContextManager(
        store,
        counter,
        settings.context,
        hybrid=HybridRetriever(LexicalRetriever(store), vector_retriever),
        vector_profile_id=embedding_profile_id,
    )

    llm = _build_llm_client(settings, llm_client, counter)
    agent = ResearchAgent(llm, store)
    pipeline = AcquisitionPipeline(
        fetch_service,
        extraction,
        Normalizer(version="1"),
        store,
        resource_store,
        indexing,
    )
    orchestrator = ResearchOrchestrator(
        store,
        search_service,
        pipeline,
        indexing,
        context_manager,
        agent,
        settings.research,
        extraction.profile_for("text/html") or "html",
        settings.tmp_root(),
        context_max_tokens=settings.context.default_budget_tokens,
        search_per_provider_limit=settings.search.per_provider_limit,
        search_total_limit=settings.search.total_limit,
    )

    event_bus = EventBus()
    conversation_service = ConversationService(
        store, orchestrator, event_bus, llm, registry, settings
    )
    application = ResearchApplication(
        store, orchestrator, settings, conversation_service, event_bus
    )
    try:
        yield application
    finally:
        await application.close()
        await search_client.aclose()
        await llm_client.aclose()
        await fetch_client.aclose()
        if embedding_http is not None:
            await embedding_http.aclose()
        if vector_index is not None:
            await vector_index.close()
        await executor.close()
