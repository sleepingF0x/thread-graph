# backend/tests/test_llm.py
from unittest.mock import patch


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
