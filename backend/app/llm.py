# backend/app/llm.py
from __future__ import annotations

import anthropic

from app.config import settings

_async_client: anthropic.AsyncAnthropic | None = None
_sync_client: anthropic.Anthropic | None = None


def get_llm_model() -> str:
    return settings.llm_model


def extract_text_content(response) -> str:
    content = getattr(response, "content", []) or []
    parts: list[str] = []

    for block in content:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            stripped = text.strip()
            if stripped:
                parts.append(stripped)

    return "\n".join(parts)


def _has_thinking_blocks(response) -> bool:
    content = getattr(response, "content", []) or []
    return any(getattr(block, "type", None) == "thinking" for block in content)


def _should_retry_for_text(response) -> bool:
    return (
        not extract_text_content(response)
        and getattr(response, "stop_reason", None) == "max_tokens"
        and _has_thinking_blocks(response)
    )


def _expanded_max_tokens(max_tokens: int) -> int:
    return min(max(max_tokens * 4, max_tokens + 128), 4096)


async def create_text_message(client, **kwargs):
    response = await client.messages.create(**kwargs)
    if _should_retry_for_text(response):
        response = await client.messages.create(
            **{**kwargs, "max_tokens": _expanded_max_tokens(kwargs["max_tokens"])}
        )
    return response


def create_sync_text_message(client, **kwargs):
    response = client.messages.create(**kwargs)
    if _should_retry_for_text(response):
        response = client.messages.create(
            **{**kwargs, "max_tokens": _expanded_max_tokens(kwargs["max_tokens"])}
        )
    return response


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
