"""Configuration loading for the intel agent."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class ModelConfig(BaseModel):
    name: str = "deepseek-chat"
    base_url: str = "https://api.deepseek.com/v1"
    api_key_env: str = "DEEPSEEK_API_KEY"


class SearchConfig(BaseModel):
    searxng_url: str | None = "http://127.0.0.1:8888"


class StorageConfig(BaseModel):
    data_dir: Path = Path("data/intel")
    raw_dir: Path = Path("data/raw")
    output_dir: Path = Path("output")


class BudgetConfig(BaseModel):
    # search_attempts/fetch_attempts mirror the original pi prototype (hard
    # cap vs sliding window, see task.py); request_limit guards total LLM API
    # spend for one run, covering both agent turns and audit judge calls.
    search_attempts: int = 6
    fetch_attempts_since_evidence: int = 6
    request_limit: int = 200


class FetchConfig(BaseModel):
    enable_httpx_fallback: bool = True


class CrawlConfig(BaseModel):
    max_depth: int = Field(default=2, ge=0)
    max_urls: int = Field(default=200, ge=1)
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
    enabled_by_default: bool = True


class WebConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = Field(default=6780, ge=1, le=65_535)


class SourcesConfig(BaseModel):
    """Known authoritative sources returned by intel_plan for direct fetch.

    Keyword-matched against each question (financial/IR/policy terms) so the
    agent can fetch vetted domains without spending search budget. Lists are
    defaults for the Chinese low-altitude-economy use case; extend per domain.
    """

    financial: list[str] = Field(
        default_factory=lambda: [
            "https://www.caixin.com",
            "https://www.cls.cn",
            "https://quote.eastmoney.com",
            "https://xueqiu.com",
        ]
    )
    ir_company: list[str] = Field(
        default_factory=lambda: [
            "https://ir.ehang.com",
            "https://www.sec.gov/edgar",
        ]
    )
    policy: list[str] = Field(
        default_factory=lambda: [
            "https://www.gov.cn",
            "https://www.ndrc.gov.cn",
        ]
    )


class Settings(BaseModel):
    """Top-level configuration; API keys are read from env, never stored here."""

    model: ModelConfig = Field(default_factory=ModelConfig)
    audit_model: ModelConfig | None = None
    search: SearchConfig = Field(default_factory=SearchConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    budgets: BudgetConfig = Field(default_factory=BudgetConfig)
    fetch: FetchConfig = Field(default_factory=FetchConfig)
    crawl: CrawlConfig = Field(default_factory=CrawlConfig)
    web: WebConfig = Field(default_factory=WebConfig)
    sources: SourcesConfig = Field(default_factory=SourcesConfig)

    def model_api_key(self) -> str | None:
        return os.environ.get(self.model.api_key_env)

    def audit_api_key(self) -> str | None:
        cfg = self.audit_model or self.model
        return os.environ.get(cfg.api_key_env)


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
