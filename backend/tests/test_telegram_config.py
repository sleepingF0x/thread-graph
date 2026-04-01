import pytest

from app.config import Settings
from app.ingestion import telegram_client


def test_settings_treat_blank_telegram_credentials_as_unset():
    settings = Settings(
        _env_file=None,
        telegram_api_id="",
        telegram_api_hash="",
    )

    assert settings.telegram_api_id is None
    assert settings.telegram_api_hash is None


@pytest.mark.asyncio
async def test_get_client_requires_configured_credentials(monkeypatch):
    telegram_client._client = None
    monkeypatch.setattr(telegram_client.settings, "telegram_api_id", None)
    monkeypatch.setattr(telegram_client.settings, "telegram_api_hash", None)

    with pytest.raises(RuntimeError, match="Telegram API credentials are not configured"):
        await telegram_client.get_client()
