"""pydantic-ai model factory: build a Model from the configured provider."""

from __future__ import annotations

import os

import httpx2
from openai import AsyncOpenAI
from pydantic_ai.models import infer_model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.ollama import OllamaProvider
from pydantic_ai.providers.openai import OpenAIProvider


def build_model(settings):
    """Build a pydantic-ai Model for the configured LLM.

    `api_style: openai` covers both DeepSeek and vLLM (OpenAI-compatible);
    `ollama` uses the native Ollama provider. The http client disables the
    ambient proxy so local endpoints are never routed through SOCKS.

    Timeout and retries come from model config. Calls stream, so the read
    timeout bounds the gap BETWEEN chunks -- a healthy long generation
    never times out, while a dead endpoint surfaces within one window.
    """
    client = httpx2.AsyncClient(
        trust_env=False,
        timeout=httpx2.Timeout(
            None,
            connect=10.0,
            read=settings.model.request_timeout_seconds,
            write=30.0,
            pool=10.0,
        ),
        http2=True,
    )
    api_key = None
    if settings.model.api_key_env:
        api_key = os.environ.get(settings.model.api_key_env)
    if settings.model.api_style == "ollama":
        provider = OllamaProvider(
            base_url=settings.model.base_url,
            api_key=api_key,
            http_client=client,
        )
        return infer_model(
            f"ollama:{settings.model.model_id}", lambda _name: provider
        )
    openai_client = AsyncOpenAI(
        base_url=settings.model.base_url,
        api_key=api_key,
        http_client=client,
        max_retries=settings.model.max_retries,
    )
    provider = OpenAIProvider(openai_client=openai_client)
    # Chat Completions, not the Responses API: infer_model defaults to the
    # latter, whose streaming + structured-output path is immature on
    # vLLM (intermittent truncated tool JSON -> validation failures on
    # ~8% of calls in production logs). chat/completions streaming has
    # been stable for the same workloads.
    return OpenAIChatModel(settings.model.model_id, provider=provider)
