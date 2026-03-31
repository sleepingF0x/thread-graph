# backend/app/main.py
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.qdrant_client import init_collections

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_collections()
    from app.ingestion.telegram_client import get_client, is_authorized
    from app.ingestion.realtime_listener import start_listener

    try:
        client = await get_client()
        if await is_authorized():
            await start_listener(client)
            logger.info("Telegram listener started")
        else:
            logger.warning("Telegram not authorized — use /auth/verify to log in.")
    except Exception as e:
        logger.warning(f"Telegram client init failed: {e}. Use /auth/verify to log in.")
    yield


app = FastAPI(title="Thread Graph", lifespan=lifespan)
app.include_router(auth_router, prefix="/auth", tags=["auth"])


@app.get("/health")
async def health():
    return {"status": "ok"}
