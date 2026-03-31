# backend/tests/test_historical_sync.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone
from uuid import uuid4


@pytest.mark.asyncio
async def test_sync_job_processes_messages(db_session):
    from app.ingestion.historical_sync import run_sync_job
    from app.models.sync_job import SyncJob
    from app.models.group import Group
    from app.models.message import Message

    # Setup: group and sync job in DB
    group = Group(id=42, name="TestGroup", type="group", is_active=True)
    db_session.add(group)
    job = SyncJob(
        id=uuid4(),
        group_id=42,
        from_ts=datetime(2026, 1, 1, tzinfo=timezone.utc),
        to_ts=datetime(2026, 1, 2, tzinfo=timezone.utc),
        status="pending",
    )
    db_session.add(job)
    await db_session.commit()

    # Mock Telethon iter_messages
    mock_msg = MagicMock()
    mock_msg.id = 1001
    mock_msg.sender_id = 7
    mock_msg.text = "test message"
    mock_msg.reply_to = None
    mock_msg.media = None
    mock_msg.date = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    mock_msg.to_json = MagicMock(return_value='{}')

    mock_client = MagicMock()
    mock_client.iter_messages = MagicMock(return_value=_async_gen([mock_msg]))

    with patch("app.ingestion.historical_sync.get_client", return_value=mock_client):
        await run_sync_job(db_session, job)

    await db_session.refresh(job)
    assert job.status == "done"

    msg = await db_session.get(Message, (1001, 42))
    assert msg is not None
    assert msg.text == "test message"


async def _async_gen(items):
    for item in items:
        yield item
