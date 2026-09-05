"""Runtime configuration, limits, and stable profile identity (T01)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from ._profile import profile_id as _profile_id

# --- stable profile identity ------------------------------------------------


def profile_id(config: Any) -> str:
    """Canonical-JSON SHA-256 over a config value (spec §4.4, §10.2).

    Key order, whitespace, and non-finite floats are normalized away so the
    same semantic config yields the same ID; version changes yield a new ID.
    """
    return _profile_id(config)


# --- per-section settings ---------------------------------------------------


class ProviderConfig(BaseModel):
    enabled: bool = True
    base_url: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class SearchConfig(BaseModel):
    provider_timeout_seconds: float = Field(default=20.0, gt=0)
    round_deadline_seconds: float = Field(default=45.0, gt=0)
    provider_attempts: int = Field(default=2, ge=1)
    per_provider_limit: int = Field(default=10, ge=1)
    total_limit: int = Field(default=20, ge=1)
    queries_per_round: int = Field(default=3, ge=1)
    tracking_params: tuple[str, ...] = (
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "gclid",
        "fbclid",
    )
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)


class FetchConfig(BaseModel):
    http_timeout_seconds: float = Field(default=30.0, gt=0)
    browser_timeout_seconds: float = Field(default=60.0, gt=0)
    item_deadline_seconds: float = Field(default=120.0, gt=0)
    attempts: int = Field(default=2, ge=1)
    global_concurrency: int = Field(default=8, ge=1)
    per_host_concurrency: int = Field(default=2, ge=1)
    per_host_rate: float = Field(default=2.0, gt=0)
    per_host_burst: int = Field(default=2, ge=1)
    browser_concurrency: int = Field(default=2, ge=1)
    normal_max_bytes: int = Field(default=50 * 1024 * 1024, gt=0)
    media_max_bytes: int = Field(default=1024 * 1024 * 1024, gt=0)
    proxy_url: str | None = None


class ExtractionConfig(BaseModel):
    cpu_concurrency: int = Field(default=2, ge=1)
    gpu_concurrency: int = Field(default=1, ge=1)
    max_backend_attempts: int = Field(default=2, ge=1)
    page_ocr_deadline_seconds: float = Field(default=120.0, gt=0)
    audio_segment_deadline_seconds: float = Field(default=180.0, gt=0)
    resource_deadline_seconds: float = Field(default=1800.0, gt=0)
    tmp_disk_bytes: int = Field(default=5 * 1024**3, gt=0)
    office_unpack_bytes: int = Field(default=500 * 1024 * 1024, gt=0)
    max_pixels: int = Field(default=25_000_000, gt=0)
    max_pdf_pages: int = Field(default=500, gt=0)
    max_media_seconds: int = Field(default=3600, gt=0)
    asr_segment_seconds: int = Field(default=30, gt=0)
    video_frame_interval_seconds: int = Field(default=5, gt=0)
    video_max_frames: int = Field(default=720, gt=0)
    ocr_languages: str = "chi_sim+eng"


class ChunkConfig(BaseModel):
    target_tokens: int = Field(default=600, gt=0)
    hard_limit_tokens: int = Field(default=900, gt=0)
    overlap_tokens: int = Field(default=80, ge=0)


class IndexingConfig(BaseModel):
    chunk: ChunkConfig = Field(default_factory=ChunkConfig)
    batch_attempts: int = Field(default=3, ge=1)
    hybrid_top_k: int = Field(default=30, ge=1)
    embedding_batch_size: int = Field(default=32, ge=1)
    rrf_constant: int = Field(default=60, ge=0)


class ContextConfig(BaseModel):
    default_budget_tokens: int = Field(default=8000, ge=0)


class ResearchConfig(BaseModel):
    max_rounds: int = Field(default=3, ge=1)
    no_progress_rounds: int = Field(default=2, ge=1)
    deadline_seconds: float = Field(default=3600.0, gt=0)
    max_llm_calls: int = Field(default=10, ge=1)
    llm_token_budget: int = Field(default=100_000, ge=1)
    new_resources_per_round: int = Field(default=20, ge=1)
    new_resources_per_task: int = Field(default=60, ge=1)


class ModelConfig(BaseModel):
    model_id: str = "deepseek-chat"
    base_url: str = "https://api.deepseek.com/v1"
    api_key_env: str | None = "DEEPSEEK_API_KEY"
    tokenizer: str | None = None
    api_style: Literal["openai", "ollama"] = "openai"
    # Disable reasoning/thinking preamble on reasoning models served by vLLM
    # (e.g. qwen3.8-27b), so the response is pure JSON.
    disable_thinking: bool = False


class EmbeddingConfig(BaseModel):
    model_id: str
    base_url: str
    api_key_env: str | None = None
    dimension: int | None = Field(default=None, gt=0)

    def profile_id(self) -> str:
        """Stable embedding profile identity: model + dimension."""
        return _profile_id(
            {"model_id": self.model_id, "dimension": self.dimension}
        )


class StorageConfig(BaseModel):
    data_dir: Path = Path("data")
    output_dir: Path = Path("output")
    sqlite_path: Path | None = None
    resources_dir: Path | None = None
    tmp_dir: Path | None = None
    logs_dir: Path | None = None
    qdrant_url: str | None = None
    import_roots: list[Path] = Field(default_factory=list)


# --- top-level settings -----------------------------------------------------


class ResearchSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: ModelConfig = Field(default_factory=ModelConfig)
    embedding: EmbeddingConfig | None = None
    search: SearchConfig = Field(default_factory=SearchConfig)
    fetch: FetchConfig = Field(default_factory=FetchConfig)
    extraction: ExtractionConfig = Field(default_factory=ExtractionConfig)
    indexing: IndexingConfig = Field(default_factory=IndexingConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)
    research: ResearchConfig = Field(default_factory=ResearchConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    # Optional capability profiles keyed by stable name -> typed payload.
    extraction_profiles: dict[str, dict[str, Any]] = Field(
        default_factory=dict
    )
    embedding_profiles: dict[str, dict[str, Any]] = Field(default_factory=dict)
    # Absolute path of the file this settings object was loaded from.
    source_path: Path | None = None

    def resolve(self, path: Path) -> Path:
        """Resolve a possibly-relative path against the config file directory."""
        if path.is_absolute():
            return path
        base = self.source_path.parent if self.source_path else Path.cwd()
        return (base / path).resolve()

    def data_root(self) -> Path:
        return self.resolve(self.storage.data_dir)

    def sqlite_file(self) -> Path:
        return self.resolve(
            self.storage.sqlite_path
            or self.storage.data_dir / "research.sqlite"
        )

    def resources_root(self) -> Path:
        return self.resolve(
            self.storage.resources_dir or self.storage.data_dir / "resources"
        )

    def tmp_root(self) -> Path:
        return self.resolve(
            self.storage.tmp_dir or self.storage.data_dir / "tmp"
        )

    def logs_root(self) -> Path:
        return self.resolve(
            self.storage.logs_dir or self.storage.data_dir / "logs"
        )

    def output_root(self) -> Path:
        return self.resolve(self.storage.output_dir)

    def import_roots(self) -> list[Path]:
        return [self.resolve(p) for p in self.storage.import_roots]


def load_settings(path: str | Path | None = None) -> ResearchSettings:
    """Load settings from a YAML file, defaulting to a bare configuration."""
    if path is None:
        env = os.environ.get("INTEL_AGENT_CONFIG")
        path = env if env else None
    if path is None:
        return ResearchSettings()
    file = Path(path)
    with open(file, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return ResearchSettings.model_validate({**data, "source_path": file})
