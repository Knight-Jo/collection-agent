"""Configuration loading for the intel agent."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class ModelConfig(BaseModel):
    name: str = "deepseek-chat"
    base_url: str = "https://api.deepseek.com/v1"
    api_key_env: str | None = "DEEPSEEK_API_KEY"


class ProviderConfig(BaseModel):
    """Tuning for one vertical provider; no secrets (admission rule)."""

    enabled: bool = True
    base_url: str | None = None
    rate_limit: float = Field(default=1.0, ge=0)
    max_results: int = Field(default=10, ge=1)
    cache_ttl: int = Field(default=3600, ge=0)


class AcademicSearchConfig(BaseModel):
    enabled: bool = True
    arxiv: bool = True
    crossref: bool = True
    semantic_scholar: bool = True
    supplement_threshold: int = Field(default=3, ge=1)
    max_results: int = Field(default=10, ge=1)
    cache_ttl: int = Field(default=3600, ge=0)


class NewsSearchConfig(BaseModel):
    enabled: bool = True
    baidu: bool = True
    # 360 News replaces the Sogou tier: news.sogou.com redirects anonymous
    # requests to an anti-spider wall, news.so.com is server-rendered.
    so360: bool = True
    # GDELT is unreachable from mainland-China networks; keep it opt-in so
    # domestic deployments never pay its timeout on every news_search.
    gdelt: bool = False
    supplement_threshold: int = Field(default=3, ge=1)
    max_results: int = Field(default=10, ge=1)
    cache_ttl: int = Field(default=3600, ge=0)


class GitHubSearchConfig(ProviderConfig):
    """GitHub capability: anonymous API, Gitee as China-accessible tier."""

    gitee: bool = True


class ArchiveSearchConfig(BaseModel):
    enabled: bool = True


class AiNativeProviderConfig(BaseModel):
    """Configuration for an optional credentialed search provider."""

    enabled: bool = False
    api_key_env: str = Field(min_length=1)
    base_url: str | None = None
    rate_limit: float = Field(default=1.0, ge=0)
    max_results: int = Field(default=10, ge=1, le=50)
    cache_ttl: int = Field(default=3600, ge=0)
    timeout_seconds: float = Field(default=15.0, gt=0)


class AiNativeSearchConfig(BaseModel):
    exa: AiNativeProviderConfig = Field(
        default_factory=lambda: AiNativeProviderConfig(
            api_key_env="EXA_API_KEY"
        )
    )
    brave: AiNativeProviderConfig = Field(
        default_factory=lambda: AiNativeProviderConfig(
            api_key_env="BRAVE_SEARCH_API_KEY"
        )
    )
    tavily: AiNativeProviderConfig = Field(
        default_factory=lambda: AiNativeProviderConfig(
            api_key_env="TAVILY_API_KEY"
        )
    )


class SearchConfig(BaseModel):
    searxng_url: str | None = "http://127.0.0.1:8888"
    ai_native: AiNativeSearchConfig = Field(
        default_factory=AiNativeSearchConfig
    )
    github: GitHubSearchConfig = Field(default_factory=GitHubSearchConfig)
    academic: AcademicSearchConfig = Field(
        default_factory=AcademicSearchConfig
    )
    news: NewsSearchConfig = Field(default_factory=NewsSearchConfig)
    archive: ArchiveSearchConfig = Field(default_factory=ArchiveSearchConfig)


class BudgetConfig(BaseModel):
    # search_attempts/fetch_attempts mirror the original pi prototype (hard
    # cap vs sliding window, see task.py); request_limit guards main-agent
    # turns. Judge calls are bounded separately by audit concurrency/timeout.
    search_attempts: int = 6
    fetch_attempts_since_evidence: int = 6
    request_limit: int = 100


class ContextConfig(BaseModel):
    """Bounds for one model request in long-running research tasks."""

    enabled: bool = True
    context_window_tokens: Literal[
        16_384, 32_768, 65_536, 131_072, 262_144
    ] = 32_768
    # Large enough for generate_research_report to emit a full structured
    # draft in one call; 1024 truncated the JSON and aborted the run (033).
    main_output_tokens: int = Field(default=8_192, ge=128)
    audit_output_tokens: int = Field(default=512, ge=128)
    disable_thinking: bool = False
    max_search_calls_before_fetch: int = Field(default=3, ge=1)
    audit_concurrency: int = Field(default=2, ge=1)
    audit_timeout_seconds: float = Field(default=60.0, gt=0)

    def history_max_bytes(self) -> int:
        """Return a conservative serialized-history budget for the window."""
        return self.context_window_tokens * 3 // 2

    def tool_content_max_bytes(self) -> int:
        """Scale one tool payload from 4 KiB to 64 KiB by window size."""
        return min(65_536, self.context_window_tokens // 4)


class FetchConfig(BaseModel):
    enable_httpx_fallback: bool = False
    enable_browser_fallback: bool = False
    browser_network_mode: Literal["validated", "isolated"] = "validated"
    browser_timeout_seconds: float = Field(default=15.0, gt=0)
    browser_max_requests: int = Field(default=40, ge=1)
    browser_max_bytes: int = Field(default=20_971_520, ge=1)
    browser_concurrency: int = Field(default=1, ge=1)


class CrawlConfig(BaseModel):
    max_depth: int = Field(default=2, ge=0)
    max_urls: int = Field(default=200, ge=1)
    # Cap on queued/fetching/complete entries per registered domain for
    # non-first-party sources; None = auto max(8, ceil(max_urls * 0.10)).
    # First-party sources (government/official) are exempt.
    per_domain_cap: int | None = Field(default=None, ge=1)
    max_total_bytes: int = Field(default=1_073_741_824, ge=1)
    max_html_bytes: int = Field(default=5_242_880, ge=1)
    max_attachment_bytes: int = Field(default=52_428_800, ge=1)
    concurrency: int = Field(default=4, ge=1)
    per_host_concurrency: int = Field(default=1, ge=1)
    per_host_delay_seconds: float = Field(default=1.0, ge=0)
    cache_ttl_hours: int = Field(default=24, ge=0)
    retries: int = Field(default=2, ge=0)
    obey_robots: bool = True
    ocr_languages: str = "chi_sim+eng"
    whisper_model: str = "small"
    enabled_by_default: bool = False


class WebConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = Field(default=6780, ge=1, le=65_535)
    auth_token_env: str | None = None
    trusted_hosts: list[str] = Field(default_factory=list)


class LoggingConfig(BaseModel):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    dir: str = "data/logs"


class SourcesConfig(BaseModel):
    """Optional deployment-specific sources returned as direct-fetch hints."""

    financial: list[str] = Field(default_factory=list)
    ir_company: list[str] = Field(default_factory=list)
    policy: list[str] = Field(default_factory=list)


class Settings(BaseModel):
    """Top-level configuration; API keys are read from env, never stored here."""

    model: ModelConfig = Field(default_factory=ModelConfig)
    audit_model: ModelConfig | None = None
    search: SearchConfig = Field(default_factory=SearchConfig)
    budgets: BudgetConfig = Field(default_factory=BudgetConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)
    fetch: FetchConfig = Field(default_factory=FetchConfig)
    crawl: CrawlConfig = Field(default_factory=CrawlConfig)
    web: WebConfig = Field(default_factory=WebConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    sources: SourcesConfig = Field(default_factory=SourcesConfig)

    def model_api_key(self) -> str | None:
        return (
            os.environ.get(self.model.api_key_env)
            if self.model.api_key_env
            else "local"
        )

    def audit_api_key(self) -> str | None:
        cfg = self.audit_model or self.model
        return os.environ.get(cfg.api_key_env) if cfg.api_key_env else "local"


def load_config(path: str | Path | None = None) -> Settings:
    """Load config.yaml (defaults to ./config.yaml when present)."""
    if path is None:
        default = Path("config.yaml")
        path = default if default.exists() else None
    if path is None:
        return Settings()
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return Settings.model_validate(data)
