# backend/app/ingestion/telegram_client.py
import asyncio
from pathlib import Path

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

from app.config import settings

_client: TelegramClient | None = None
_phone_code_hash: str | None = None
_pending_phone: str | None = None


def _get_dialog_type(dialog) -> str:
    entity = dialog.entity
    if getattr(entity, "broadcast", False):
        return "channel"
    if getattr(entity, "megagroup", False) or getattr(entity, "gigagroup", False):
        return "supergroup"
    if getattr(dialog, "is_group", False):
        return "group"
    if getattr(dialog, "is_user", False):
        return "user"
    return "unknown"


def _normalize_dialog(dialog) -> dict:
    dialog_type = _get_dialog_type(dialog)
    return {
        "raw_id": getattr(dialog.entity, "id", None),
        "dialog_id": dialog.id,
        "name": dialog.name,
        "username": getattr(dialog.entity, "username", None),
        "type": dialog_type,
        "is_group_like": dialog_type in {"group", "supergroup", "channel"},
    }


def has_credentials() -> bool:
    return settings.telegram_api_id is not None and bool(settings.telegram_api_hash)


def _require_configured_credentials() -> tuple[int, str]:
    if not has_credentials():
        raise RuntimeError(
            "Telegram API credentials are not configured. "
            "Set TELEGRAM_API_ID and TELEGRAM_API_HASH in .env."
        )
    return settings.telegram_api_id, settings.telegram_api_hash


def _make_client() -> TelegramClient:
    api_id, api_hash = _require_configured_credentials()
    Path(settings.session_path).parent.mkdir(parents=True, exist_ok=True)
    return TelegramClient(
        settings.session_path,
        api_id,
        api_hash,
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


async def list_available_dialogs() -> list[dict]:
    client = await get_client()
    dialogs: list[dict] = []
    async for dialog in client.iter_dialogs():
        dialogs.append(_normalize_dialog(dialog))
    return dialogs


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
