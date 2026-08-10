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
    api_key_env: str = "DEEPSEEK_API_KEY"


class SearchConfig(BaseModel):
    searxng_url: str | None = "http://127.0.0.1:8888"


class StorageConfig(BaseModel):
    data_dir: Path = Path("data/intel")
    raw_dir: Path = Path("data/raw")
    output_dir: Path = Path("output")


class BudgetConfig(BaseModel):
    search_attempts: int = 6
    fetch_attempts_since_evidence: int = 6
    request_limit: int = 200


class Settings(BaseModel):
    model: ModelConfig = Field(default_factory=ModelConfig)
    audit_model: ModelConfig | None = None
    search: SearchConfig = Field(default_factory=SearchConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    budgets: BudgetConfig = Field(default_factory=BudgetConfig)

    def model_api_key(self) -> str | None:
        return os.environ.get(self.model.api_key_env)

    def audit_api_key(self) -> str | None:
        cfg = self.audit_model or self.model
        return os.environ.get(cfg.api_key_env)


def load_config(path: str | Path | None = None) -> Settings:
    if path is None:
        default = Path("config.yaml")
        path = default if default.exists() else None
    if path is None:
        return Settings()
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return Settings.model_validate(data)
