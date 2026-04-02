# backend/tests/test_llm.py
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest


def test_get_sync_anthropic_client_passes_base_url():
    from app.llm import get_sync_anthropic_client

    with patch("app.llm._sync_client", None), \
         patch("app.llm.settings.anthropic_api_key", "test-key"), \
         patch("app.llm.settings.anthropic_base_url", "https://anthropic-proxy.example.com"), \
         patch("app.llm.anthropic.Anthropic") as mock_anthropic:
        get_sync_anthropic_client()

    mock_anthropic.assert_called_once_with(
        api_key="test-key",
        base_url="https://anthropic-proxy.example.com",
    )


def test_get_sync_anthropic_client_omits_empty_base_url():
    from app.llm import get_sync_anthropic_client

    with patch("app.llm._sync_client", None), \
         patch("app.llm.settings.anthropic_api_key", "test-key"), \
         patch("app.llm.settings.anthropic_base_url", ""), \
         patch("app.llm.anthropic.Anthropic") as mock_anthropic:
        get_sync_anthropic_client()

    mock_anthropic.assert_called_once_with(api_key="test-key")


def test_get_llm_model_reads_settings():
    from app.llm import get_llm_model

    with patch("app.llm.settings.llm_model", "claude-3-5-haiku-20241022"):
        assert get_llm_model() == "claude-3-5-haiku-20241022"


def test_extract_text_content_skips_empty_blocks():
    from app.llm import extract_text_content

    response = SimpleNamespace(
        content=[
            SimpleNamespace(text=None),
            SimpleNamespace(text=""),
            SimpleNamespace(text="  final answer  "),
        ]
    )

    assert extract_text_content(response) == "final answer"


@pytest.mark.asyncio
async def test_create_text_message_retries_when_response_only_contains_thinking():
    from app.llm import create_text_message

    thinking_only = SimpleNamespace(
        content=[SimpleNamespace(type="thinking", text=None)],
        stop_reason="max_tokens",
    )
    with_text = SimpleNamespace(
        content=[
            SimpleNamespace(type="thinking", text=None),
            SimpleNamespace(type="text", text="final answer"),
        ],
        stop_reason="end_turn",
    )
    client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(side_effect=[thinking_only, with_text])))

    response = await create_text_message(
        client,
        model="test-model",
        max_tokens=64,
        messages=[{"role": "user", "content": "hello"}],
    )

    assert response is with_text
    assert client.messages.create.await_count == 2
    retry_kwargs = client.messages.create.await_args_list[1].kwargs
    assert retry_kwargs["max_tokens"] == 256


def test_create_sync_text_message_retries_when_response_only_contains_thinking():
    from app.llm import create_sync_text_message

    thinking_only = SimpleNamespace(
        content=[SimpleNamespace(type="thinking", text=None)],
        stop_reason="max_tokens",
    )
    with_text = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="final answer")],
        stop_reason="end_turn",
    )
    create = Mock(side_effect=[thinking_only, with_text])
    client = SimpleNamespace(messages=SimpleNamespace(create=create))

    response = create_sync_text_message(
        client,
        model="test-model",
        max_tokens=64,
        messages=[{"role": "user", "content": "hello"}],
    )

    assert response is with_text
    assert create.call_count == 2
    retry_kwargs = create.call_args_list[1].kwargs
    assert retry_kwargs["max_tokens"] == 256
