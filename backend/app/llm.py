# backend/app/llm.py
from __future__ import annotations

import anthropic

from app.config import settings

_async_client: anthropic.AsyncAnthropic | None = None
_sync_client: anthropic.Anthropic | None = None


def get_llm_model() -> str:
    return settings.llm_model


def _anthropic_client_kwargs() -> dict:
    kwargs = {"api_key": settings.anthropic_api_key}
    if settings.anthropic_base_url:
        kwargs["base_url"] = settings.anthropic_base_url
    return kwargs


def get_sync_anthropic_client() -> anthropic.Anthropic:
    global _sync_client
    if _sync_client is None:
        _sync_client = anthropic.Anthropic(**_anthropic_client_kwargs())
    return _sync_client


def get_async_anthropic_client() -> anthropic.AsyncAnthropic:
    global _async_client
    if _async_client is None:
        _async_client = anthropic.AsyncAnthropic(**_anthropic_client_kwargs())
    return _async_client
