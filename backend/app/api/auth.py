# backend/app/api/auth.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.ingestion.telegram_client import (
    has_credentials,
    is_authorized,
    list_available_dialogs,
    send_code,
    sign_in,
)

router = APIRouter()


class SendCodeRequest(BaseModel):
    phone: str


class VerifyRequest(BaseModel):
    code: str
    password: str | None = None


@router.get("/status")
async def auth_status():
    if not has_credentials():
        return {
            "authorized": False,
            "configured": False,
            "detail": (
                "Telegram API credentials are not configured. "
                "Set TELEGRAM_API_ID and TELEGRAM_API_HASH in .env."
            ),
        }

    try:
        authorized = await is_authorized()
    except Exception:
        authorized = False
    return {"authorized": authorized, "configured": True, "detail": None}


@router.post("/login")
async def login(req: SendCodeRequest):
    try:
        phone_code_hash = await send_code(req.phone)
        return {"phone_code_hash": phone_code_hash, "message": "Code sent"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/verify")
async def verify(req: VerifyRequest):
    try:
        success = await sign_in(req.code, req.password)
        return {"authorized": success}
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/dialogs")
async def dialogs():
    if not has_credentials():
        raise HTTPException(
            status_code=400,
            detail=(
                "Telegram API credentials are not configured. "
                "Set TELEGRAM_API_ID and TELEGRAM_API_HASH in .env."
            ),
        )

    if not await is_authorized():
        raise HTTPException(status_code=401, detail="Telegram not authorized")

    return await list_available_dialogs()
