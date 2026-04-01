# backend/tests/test_realtime_listener.py
import pytest
from unittest.mock import MagicMock
from datetime import datetime, timezone


@pytest.mark.asyncio
async def test_save_message_inserts_row(db_session):
    from app.ingestion.realtime_listener import save_message
    from app.models.message import Message, PendingSliceMessage
    from app.models.group import Group

    # FK requirement: group must exist before inserting message
    group = Group(id=99, name="TestGroup", type="group", is_active=True)
    db_session.add(group)
    await db_session.commit()

    mock_msg = MagicMock()
    mock_msg.id = 12345
    mock_msg.sender_id = 1
    mock_msg.text = "hello world"
    mock_msg.reply_to = None
    mock_msg.media = None
    mock_msg.date = datetime(2026, 1, 1, tzinfo=timezone.utc)
    mock_msg.to_json = MagicMock(return_value='{}')

    await save_message(db_session, mock_msg, group_id=99)

    result = await db_session.get(Message, (12345, 99))
    assert result is not None
    assert result.text == "hello world"
    assert result.group_id == 99

    pending = await db_session.get(PendingSliceMessage, (99, 12345))
    assert pending is not None
    assert pending.ts == datetime(2026, 1, 1, tzinfo=timezone.utc)
