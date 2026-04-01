# backend/app/ingestion/realtime_listener.py
import json
import logging
from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from telethon import TelegramClient, events
from telethon.tl.types import Message as TelethonMessage

from app.database import AsyncSessionLocal
from app.models.group import Group
from app.models.message import Message

logger = logging.getLogger(__name__)


def _get_group_id(message: TelethonMessage) -> int | None:
    peer = message.peer_id
    if hasattr(peer, "channel_id"):
        return peer.channel_id
    if hasattr(peer, "chat_id"):
        return peer.chat_id
    return None


def _get_message_type(message: TelethonMessage) -> str:
    if message.media is not None:
        return "media"
    if message.text:
        return "text"
    return "service"


async def save_message(
    session: AsyncSession, message: TelethonMessage, group_id: int
) -> None:
    reply_to_id = None
    if message.reply_to:
        reply_to_id = getattr(message.reply_to, "reply_to_msg_id", None)

    stmt = insert(Message).values(
        id=message.id,
        group_id=group_id,
        sender_id=message.sender_id,
        text=message.text or "",
        reply_to_id=reply_to_id,
        reply_to_group_id=group_id if reply_to_id else None,
        message_type=_get_message_type(message),
        raw_json=json.loads(message.to_json()),
        is_deleted=False,
        ts=(
            message.date if message.date.tzinfo is not None
            else message.date.replace(tzinfo=timezone.utc)
        ) if message.date else datetime.now(timezone.utc),
    ).on_conflict_do_nothing(index_elements=["id", "group_id"])

    await session.execute(stmt)


async def start_listener(client: TelegramClient) -> None:
    @client.on(events.NewMessage)
    async def handler(event):
        group_id = _get_group_id(event.message)
        if group_id is None:
            return
        async with AsyncSessionLocal() as session:
            group = await session.get(Group, group_id)
            if group is None or not group.is_active:
                return
            await save_message(session, event.message, group_id)
            await session.commit()
            logger.info(f"Saved message {event.message.id} from group {group_id}")

    logger.info("Real-time listener started")
