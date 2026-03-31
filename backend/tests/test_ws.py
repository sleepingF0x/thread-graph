import json
import threading
from unittest.mock import AsyncMock, patch

import pytest
from starlette.testclient import TestClient

# Patch all external services before the app's lifespan fires so the
# TestClient can start without a running Qdrant or Telegram.
_STARTUP_PATCHES = [
    # init_collections is imported at the top of main.py so patch it there
    patch("app.main.init_collections", new_callable=AsyncMock),
    # these are imported locally inside the lifespan, so patch at source
    patch("app.ingestion.telegram_client.get_client", new_callable=AsyncMock),
    patch("app.ingestion.telegram_client.is_authorized", new=AsyncMock(return_value=False)),
    patch("app.ingestion.historical_sync.sync_worker_loop", new_callable=AsyncMock),
    patch("app.worker.processor.pending_slice_loop", new_callable=AsyncMock),
    patch("app.worker.processor.pipeline_loop", new_callable=AsyncMock),
]


@pytest.fixture(scope="module")
def client():
    for p in _STARTUP_PATCHES:
        p.start()
    from app.main import app
    with TestClient(app) as c:
        yield c
    for p in _STARTUP_PATCHES:
        p.stop()


def test_websocket_connect_and_receive(client):
    """Connect to WS, broadcast an event, verify it is received."""
    with client.websocket_connect("/ws/realtime") as ws:
        from app.api.ws import manager

        def do_broadcast():
            import asyncio
            loop = asyncio.new_event_loop()
            loop.run_until_complete(
                manager.broadcast("test_event", {"key": "value"}, "test-key")
            )
            loop.close()

        t = threading.Thread(target=do_broadcast)
        t.start()
        t.join(timeout=5)

        msg = ws.receive_text()
        data = json.loads(msg)
        assert data["event"] == "test_event"
        assert data["payload"]["key"] == "value"
        assert data["dedup_key"] == "test-key"


def test_websocket_broadcast_format(client):
    """Verify JSON shape of broadcast messages."""
    with client.websocket_connect("/ws/realtime") as ws:
        from app.api.ws import manager

        def do_broadcast():
            import asyncio
            loop = asyncio.new_event_loop()
            loop.run_until_complete(
                manager.broadcast("topic_updated", {"topic_id": "abc"}, "dedup-123")
            )
            loop.close()

        t = threading.Thread(target=do_broadcast)
        t.start()
        t.join(timeout=5)

        msg = ws.receive_text()
        data = json.loads(msg)
        assert "event" in data
        assert "payload" in data
        assert "dedup_key" in data
