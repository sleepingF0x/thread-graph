from unittest.mock import AsyncMock, patch

import pytest
from starlette.testclient import TestClient

from app.ingestion import telegram_client

_STARTUP_PATCHES = [
    patch("app.main.init_collections", new_callable=AsyncMock),
    patch("app.ingestion.realtime_listener.start_listener", new_callable=AsyncMock),
    patch("app.ingestion.historical_sync.sync_worker_loop", new_callable=AsyncMock),
    patch("app.worker.processor.pending_slice_loop", new_callable=AsyncMock),
    patch("app.worker.processor.pipeline_loop", new_callable=AsyncMock),
]

CONFIG_ERROR = (
    "Telegram API credentials are not configured. "
    "Set TELEGRAM_API_ID and TELEGRAM_API_HASH in .env."
)


def _make_client(monkeypatch) -> TestClient:
    for p in _STARTUP_PATCHES:
        p.start()

    from app.main import app

    return TestClient(app)


@pytest.fixture
def client(monkeypatch):
    telegram_client._client = None
    monkeypatch.setattr(telegram_client.settings, "telegram_api_id", None)
    monkeypatch.setattr(telegram_client.settings, "telegram_api_hash", None)

    with _make_client(monkeypatch) as test_client:
        yield test_client

    for p in reversed(_STARTUP_PATCHES):
        p.stop()


@pytest.fixture
def authorized_client(monkeypatch):
    telegram_client._client = None
    monkeypatch.setattr(telegram_client.settings, "telegram_api_id", 12345)
    monkeypatch.setattr(telegram_client.settings, "telegram_api_hash", "hash")

    with patch("app.ingestion.telegram_client.is_authorized", new=AsyncMock(return_value=True)), \
         patch("app.ingestion.telegram_client.get_client", new_callable=AsyncMock):
        with _make_client(monkeypatch) as test_client:
            yield test_client

    for p in reversed(_STARTUP_PATCHES):
        p.stop()


def test_auth_status_reports_missing_telegram_config(client):
    response = client.get("/auth/status")

    assert response.status_code == 200
    assert response.json() == {
        "authorized": False,
        "configured": False,
        "detail": CONFIG_ERROR,
    }


def test_login_returns_missing_telegram_config_error(client):
    response = client.post("/auth/login", json={"phone": "+85252932604"})

    assert response.status_code == 400
    assert response.json() == {"detail": CONFIG_ERROR}


def test_auth_dialogs_returns_normalized_dialogs_for_authorized_session(authorized_client):
    mock_dialogs = [
        {
            "raw_id": 2317243383,
            "dialog_id": -1002317243383,
            "name": "Walrus 中文官方群",
            "username": "WalrusChinese",
            "type": "supergroup",
            "is_group_like": True,
        },
        {
            "raw_id": 123456789,
            "dialog_id": 123456789,
            "name": "Alice",
            "username": "alice",
            "type": "user",
            "is_group_like": False,
        },
    ]

    with patch(
        "app.api.auth.list_available_dialogs",
        new=AsyncMock(return_value=mock_dialogs),
    ):
        response = authorized_client.get("/auth/dialogs")

    assert response.status_code == 200
    assert response.json() == mock_dialogs


def test_auth_dialogs_requires_authorized_telegram_session(authorized_client):
    with patch("app.api.auth.is_authorized", new=AsyncMock(return_value=False)):
        response = authorized_client.get("/auth/dialogs")

    assert response.status_code == 401
    assert response.json() == {"detail": "Telegram not authorized"}
