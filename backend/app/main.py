# backend/app/main.py
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.qdrant_client import init_collections


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_collections()
    yield


app = FastAPI(title="Thread Graph", lifespan=lifespan)
app.include_router(auth_router, prefix="/auth", tags=["auth"])


@app.get("/health")
async def health():
    return {"status": "ok"}
