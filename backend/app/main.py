# backend/app/main.py
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.api.groups import router as groups_router
from app.api.terms import router as terms_router
from app.api.topics import router as topics_router
from app.qdrant_client import init_collections

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_collections()

    from app.ingestion.telegram_client import get_client, is_authorized
    from app.ingestion.realtime_listener import start_listener
    from app.ingestion.historical_sync import sync_worker_loop
    from app.worker.processor import pending_slice_loop, pipeline_loop

    try:
        client = await get_client()
        if await is_authorized():
            await start_listener(client)
            logger.info("Telegram listener started")
        else:
            logger.warning("Telegram not authorized — use /auth/verify to log in.")
    except Exception as e:
        logger.warning(f"Telegram client init failed: {e}")

    asyncio.create_task(sync_worker_loop())
    asyncio.create_task(pending_slice_loop())
    asyncio.create_task(pipeline_loop())
    yield


app = FastAPI(title="Thread Graph", lifespan=lifespan)
app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(groups_router, prefix="/groups", tags=["groups"])
app.include_router(topics_router, tags=["topics"])
app.include_router(terms_router, prefix="/terms", tags=["terms"])


@app.get("/health")
async def health():
    return {"status": "ok"}
