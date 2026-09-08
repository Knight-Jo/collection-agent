"""Build the research application and its runtime dependencies."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx2

from .acquisition import AcquisitionPipeline
from .agent.models import build_model
from .agent.roles import build_roles
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
from .factcheck.service import FactCheckService
from .fetch.browser import BrowserFetcher
from .fetch.service import FetchService
from .fetch.transport import build_client as build_fetch_client
from .indexing.embedding import HttpEmbeddingClient
from .indexing.qdrant import QdrantVectorIndex
from .indexing.service import IndexingService
from .indexing.tokenize import TiktokenCounter
from .library import Library
from .media.service import MediaService
from .monitoring.gates import WatchGate
from .monitoring.service import MonitoringService
from .normalization import Normalizer
from .orchestration.orchestrator import ResearchOrchestrator
from .runtime.config import ResearchSettings
from .runtime.events import EventBus
from .runtime.execution import Executor
from .runtime.logging import configure_logging
from .search.providers import (
    ArxivProvider,
    BraveProvider,
    ExaProvider,
    OpenAlexProvider,
    RssProvider,
    SearXNGProvider,
    TavilyProvider,
)
from .search.service import SearchService
from .search.settings import SearchSettings
from .storage.factcheck import FactCheckStore
from .storage.materials import MaterialStore
from .storage.media import MediaStore
from .storage.monitoring import MonitoringStore
from .storage.resources import ResourceStore
from .storage.settings import SettingsStore
from .storage.sqlite import SqliteStore
from .storage.tasks import TaskStore


def _resolve_api_key(cfg):
    if cfg.api_key_env:
        import os

        key = os.environ.get(cfg.api_key_env)
        if key:
            return key
    return cfg.api_key


def build_search_providers(settings: ResearchSettings, client, state=None):
    """Return the search providers enabled in ``settings``.

    ``client`` is the shared HTTP client used by the providers for requests.
    ``state`` is an optional callable ``key -> dict`` supplying runtime
    overrides (enabled/cookies/api_key) from the writable state store.
    """

    def override(key: str) -> dict:
        if state is None:
            return {}
        value = state(key)
        return value if isinstance(value, dict) else {}

    def enabled(name: str, default: bool, ai: bool = False) -> bool:
        key = f"ai_tool:{name}" if ai else f"search_source:{name}"
        return override(key).get("enabled", default)

    def api_key(name: str, cfg) -> str | None:
        value = override(f"ai_tool:{name}").get("api_key")
        if value:
            return value
        return _resolve_api_key(cfg)

    providers = []
    cfg = settings.search.providers
    if cfg.get("searxng", None) is not None and enabled(
        "searxng", cfg["searxng"].enabled
    ):
        p = cfg["searxng"]
        providers.append(
            SearXNGProvider(client, p.base_url or "http://127.0.0.1:8888")
        )
    if cfg.get("exa", None) is not None and enabled(
        "exa", cfg["exa"].enabled, ai=True
    ):
        extra = cfg["exa"].extra
        providers.append(
            ExaProvider(
                client,
                api_key=api_key("exa", cfg["exa"]),
                base_url=extra.get("base_url") or "https://api.exa.ai/search",
                num_results=extra.get("num_results", 10),
            )
        )
    if cfg.get("tavily", None) is not None and enabled(
        "tavily", cfg["tavily"].enabled, ai=True
    ):
        extra = cfg["tavily"].extra
        providers.append(
            TavilyProvider(
                client,
                api_key=api_key("tavily", cfg["tavily"]),
                base_url=extra.get("base_url")
                or "https://api.tavily.com/search",
                search_depth=extra.get("search_depth", "advanced"),
                max_results=extra.get("max_results", 10),
            )
        )
    if cfg.get("brave", None) is not None and enabled(
        "brave", cfg["brave"].enabled, ai=True
    ):
        extra = cfg["brave"].extra
        providers.append(
            BraveProvider(
                client,
                api_key=api_key("brave", cfg["brave"]),
                base_url=extra.get("base_url")
                or "https://api.search.brave.com/res/v1/web/search",
            )
        )
    if cfg.get("arxiv", None) is not None and enabled(
        "arxiv", cfg["arxiv"].enabled
    ):
        providers.append(ArxivProvider(client))
    if cfg.get("openalex", None) is not None and enabled(
        "openalex", cfg["openalex"].enabled
    ):
        providers.append(
            OpenAlexProvider(
                client,
                base_url=cfg["openalex"].base_url
                or "https://api.openalex.org/works",
            )
        )
    if cfg.get("rss", None) is not None and enabled("rss", cfg["rss"].enabled):
        providers.append(
            RssProvider(client, feeds=cfg["rss"].extra.get("feeds", []))
        )
    return providers


def _build_embedding(settings):
    if settings.embedding is None:
        return None, None, None
    client = httpx2.AsyncClient(
        base_url=settings.embedding.base_url,
        trust_env=False,
        timeout=60.0,
        http2=True,
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
) -> AsyncGenerator[ResearchApplication]:
    """Build the research application from the supplied settings.

    The setup creates shared stores and executors, registers extraction and
    search services, configures indexing and retrieval, then assembles the
    research workflow and application API. Use it as an asynchronous context
    manager; all resources are released when the context exits.

    creates the following services and components:
    - MaterialStore: SQLite-backed store for artifacts, documents, and chunks.
    - ResourceStore: File-backed store for downloaded and extracted resources.
    - Executor: Resource-aware execution pool for CPU and GPU tasks.
    - ExtractionService: Manages extraction backends and profiles.
    - FetchService: Fetches and downloads artifacts from URLs.
    - SearchService: Searches for documents using configured providers.
    - IndexingService: Indexes and retrieves chunks, optionally with vector search.
    - ContextManager: Manages context retrieval and hybrid search.


    Args:
        settings: Runtime configuration for all assembled services.
    """
    configure_logging(
        settings.logging.level,
        settings.logs_root(),
        console=settings.logging.console,
        file=settings.logging.file,
    )
    logger = logging.getLogger("intel_agent.bootstrap")
    logger.info(
        "starting research application (model=%s, qdrant=%s)",
        settings.model.model_id,
        settings.storage.qdrant_url,
    )

    # Create the shared stores and resource-aware execution pool first.
    sqlite = SqliteStore(settings.sqlite_file())
    store = MaterialStore(sqlite)
    task_store = TaskStore(sqlite)
    settings_store = SettingsStore(sqlite)
    resource_store = ResourceStore(
        settings.resources_root(),
        settings.import_roots() + [settings.tmp_root()],
        store,
    )
    executor = Executor(
        cpu_concurrency=settings.extraction.cpu_concurrency,
        gpu_concurrency=settings.extraction.gpu_concurrency,
    )

    # Register every extraction backend before building the extraction service.
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

    # Fetching and searching use separate clients because their timeouts differ.
    fetch_client = build_fetch_client(
        timeout=settings.fetch.http_timeout_seconds,
        proxy=settings.fetch.proxy_url,
    )
    search_client = httpx2.AsyncClient(
        trust_env=False,
        timeout=settings.search.provider_timeout_seconds,
        http2=True,
    )

    fetch_service = FetchService(
        fetch_client,
        resource_store,
        settings.fetch,
        BrowserFetcher(resource_store),
    )
    search_service = SearchService(
        build_search_providers(settings, search_client, settings_store.get),
        settings.search,
    )
    logger.info(
        "search providers: %s",
        sorted(search_service.providers) or ["<none>"],
    )

    # Build indexing and retrieval, enabling vector search only when configured.
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

    # Assemble the research workflow and expose it through the application API.
    roles = build_roles(build_model(settings), settings)
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
        roles,
        settings.research,
        extraction.profile_for("text/html") or "html",
        settings.tmp_root(),
        context_max_tokens=settings.context.default_budget_tokens,
        search_per_provider_limit=settings.search.per_provider_limit,
        search_total_limit=settings.search.total_limit,
    )

    event_bus = EventBus()

    def rebuild_providers():
        return build_search_providers(
            settings, search_client, settings_store.get
        )

    conversation_service = ConversationService(
        store,
        orchestrator,
        event_bus,
        roles,
        registry,
        settings,
        rebuild_providers,
    )
    application = ResearchApplication(
        store,
        task_store,
        orchestrator,
        settings,
        conversation_service,
        event_bus,
    )

    # Workspace extensions: writable search config, monitoring, fact-check,
    # media analysis, and the read-only library projection.
    search_settings = SearchSettings(settings, settings_store)
    monitoring_store = MonitoringStore(sqlite)
    monitoring = MonitoringService(
        monitoring_store,
        task_store,
        orchestrator,
        application,
        settings,
        gate=WatchGate(fetch_service, extraction, monitoring_store),
    )
    factcheck = FactCheckService(
        FactCheckStore(sqlite),
        task_store,
        orchestrator,
        application,
        settings,
    )
    media = MediaService(
        MediaStore(sqlite),
        task_store,
        store,
        pipeline,
        application,
        settings,
        roles,
    )
    library = Library(conversation_service, monitoring, factcheck, media)

    application.search_settings = search_settings
    application.monitoring = monitoring
    application.factcheck = factcheck
    application.media = media
    application.library = library
    application.material_store = store
    application.settings_store = settings_store
    application.resource_store = resource_store
    try:
        yield application
    finally:
        # Close the application before its shared clients and execution pool.
        await application.close()
        await search_client.aclose()
        await fetch_client.aclose()
        if embedding_http is not None:
            await embedding_http.aclose()
        if vector_index is not None:
            await vector_index.close()
        await executor.close()
        logger.info("research application stopped")
