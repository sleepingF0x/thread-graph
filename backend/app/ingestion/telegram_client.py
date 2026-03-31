# backend/app/ingestion/telegram_client.py
import asyncio
from pathlib import Path

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

from app.config import settings

_client: TelegramClient | None = None
_phone_code_hash: str | None = None
_pending_phone: str | None = None


def _make_client() -> TelegramClient:
    Path(settings.session_path).parent.mkdir(parents=True, exist_ok=True)
    return TelegramClient(
        settings.session_path,
        settings.telegram_api_id,
        settings.telegram_api_hash,
    )


async def get_client() -> TelegramClient:
    global _client
    if _client is None:
        _client = _make_client()
        await _client.connect()
    return _client


async def is_authorized() -> bool:
    client = await get_client()
    return await client.is_user_authorized()


async def send_code(phone: str) -> str:
    """Returns phone_code_hash needed for sign_in."""
    global _phone_code_hash, _pending_phone
    client = await get_client()
    result = await client.send_code_request(phone)
    _phone_code_hash = result.phone_code_hash
    _pending_phone = phone
    return result.phone_code_hash


async def sign_in(code: str, password: str | None = None) -> bool:
    """Sign in with verification code. If 2FA required, pass password."""
    global _phone_code_hash, _pending_phone
    client = await get_client()
    try:
        await client.sign_in(_pending_phone, code, phone_code_hash=_phone_code_hash)
    except SessionPasswordNeededError:
        if password is None:
            raise ValueError("2FA password required")
        await client.sign_in(password=password)
    return await client.is_user_authorized()


async def disconnect() -> None:
    global _client
    if _client is not None:
        await _client.disconnect()
        _client = None
