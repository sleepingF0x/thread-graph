# backend/app/main.py
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.auth import router as auth_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: ingestion worker will be added in Task 8
    yield
    # Shutdown


app = FastAPI(title="Thread Graph", lifespan=lifespan)
app.include_router(auth_router, prefix="/auth", tags=["auth"])


@app.get("/health")
async def health():
    return {"status": "ok"}
