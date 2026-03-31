import json
import threading

import pytest
from starlette.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


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
