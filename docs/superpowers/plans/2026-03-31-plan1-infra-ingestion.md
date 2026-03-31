# Thread Graph — Plan 1: Infrastructure + Telegram Ingestion

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the full persistence layer (PostgreSQL + Qdrant) and a working Telegram ingestion system (login, real-time listener, historical sync) that stores messages into the database.

**Architecture:** Single-repo monorepo with `backend/` (Python/FastAPI) and `frontend/` (React). Plan 1 covers only the backend: Docker Compose infra, DB schema + migrations, Telethon auth flow, real-time message listener, and historical sync worker. No processing pipeline yet — messages land in the DB, ready for Plan 2.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0 (async), asyncpg, Alembic, Telethon, qdrant-client, pydantic-settings, pytest + pytest-asyncio

---

## File Structure

```
thread-graph/
├── docker-compose.yml
├── .env.example
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── alembic.ini
│   ├── alembic/
│   │   └── versions/
│   │       └── 001_initial_schema.py
│   ├── app/
│   │   ├── main.py                  # FastAPI app + lifespan (starts worker tasks)
│   │   ├── config.py                # pydantic-settings, all env vars
│   │   ├── database.py              # async SQLAlchemy engine + session factory
│   │   ├── qdrant_client.py         # Qdrant client wrapper + collection init
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── group.py             # Group ORM model
│   │   │   ├── message.py           # Message ORM model
│   │   │   ├── slice.py             # Slice + SliceMessage ORM models
│   │   │   ├── topic.py             # Topic + SliceTopic ORM models
│   │   │   ├── term.py              # Term ORM model
│   │   │   └── sync_job.py          # SyncJob ORM model + QaSession + QaContext
│   │   ├── ingestion/
│   │   │   ├── __init__.py
│   │   │   ├── telegram_client.py   # Telethon wrapper: login, session, send/recv
│   │   │   ├── realtime_listener.py # Telethon event handler → writes messages
│   │   │   └── historical_sync.py   # Pulls message history for a sync_job
│   │   └── api/
│   │       ├── __init__.py
│   │       └── auth.py              # /auth/status, /auth/login, /auth/verify
│   └── tests/
│       ├── conftest.py              # pytest fixtures: test DB, mock Telethon
│       ├── test_historical_sync.py
│       └── test_realtime_listener.py
└── frontend/                        # scaffold only in Plan 1 (empty React app)
    └── package.json
```

---

## Task 1: Docker Compose + Project Scaffold

**Files:**
- Create: `docker-compose.yml`
- Create: `.env.example`
- Create: `backend/requirements.txt`
- Create: `backend/Dockerfile`

- [ ] **Step 1: Create docker-compose.yml**

```yaml
# docker-compose.yml
version: "3.9"

services:
  postgres:
    image: postgres:15
    environment:
      POSTGRES_USER: threadgraph
      POSTGRES_PASSWORD: threadgraph
      POSTGRES_DB: threadgraph
    volumes:
      - pgdata:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U threadgraph"]
      interval: 5s
      timeout: 5s
      retries: 5

  qdrant:
    image: qdrant/qdrant:latest
    volumes:
      - qdrantdata:/qdrant/storage
    ports:
      - "6333:6333"
      - "6334:6334"

  backend:
    build: ./backend
    depends_on:
      postgres:
        condition: service_healthy
      qdrant:
        condition: service_started
    environment:
      - DATABASE_URL=postgresql+asyncpg://threadgraph:threadgraph@postgres:5432/threadgraph
      - QDRANT_HOST=qdrant
      - QDRANT_PORT=6333
    env_file: .env
    volumes:
      - ./backend:/app
      - ./telegram_session:/app/session
    ports:
      - "8000:8000"
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

volumes:
  pgdata:
  qdrantdata:
```

- [ ] **Step 2: Create .env.example**

```bash
# .env.example
TELEGRAM_API_ID=
TELEGRAM_API_HASH=

ANTHROPIC_API_KEY=

EMBEDDING_BASE_URL=https://api.openai.com/v1
EMBEDDING_API_KEY=
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIM=1536

DATABASE_URL=postgresql+asyncpg://threadgraph:threadgraph@postgres:5432/threadgraph

QDRANT_HOST=qdrant
QDRANT_PORT=6333
```

Copy to `.env` and fill in values.

- [ ] **Step 3: Create backend/requirements.txt**

```
fastapi==0.115.0
uvicorn[standard]==0.30.6
sqlalchemy[asyncio]==2.0.36
asyncpg==0.30.0
alembic==1.14.0
telethon==1.37.0
anthropic==0.40.0
openai==1.58.0
qdrant-client==1.12.0
pydantic-settings==2.6.1
pydantic==2.10.3
pytest==8.3.4
pytest-asyncio==0.24.0
pytest-mock==3.14.0
httpx==0.28.1
```

- [ ] **Step 4: Create backend/Dockerfile**

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
```

- [ ] **Step 5: Start infra and verify**

```bash
cp .env.example .env
# fill in at minimum TELEGRAM_API_ID and TELEGRAM_API_HASH
docker compose up postgres qdrant -d
docker compose ps
```

Expected: postgres and qdrant showing "healthy" / "running".

- [ ] **Step 6: Commit**

```bash
git add docker-compose.yml .env.example backend/requirements.txt backend/Dockerfile
git commit -m "feat: project scaffold with docker-compose and backend dependencies"
```

---

## Task 2: Config + Database Setup

**Files:**
- Create: `backend/app/config.py`
- Create: `backend/app/database.py`
- Create: `backend/app/main.py`

- [ ] **Step 1: Write config.py**

```python
# backend/app/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    telegram_api_id: int
    telegram_api_hash: str

    anthropic_api_key: str

    embedding_base_url: str = "https://api.openai.com/v1"
    embedding_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536

    database_url: str
    qdrant_host: str = "qdrant"
    qdrant_port: int = 6333

    session_path: str = "session/threadgraph"


settings = Settings()
```

- [ ] **Step 2: Write database.py**

```python
# backend/app/database.py
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

engine = create_async_engine(settings.database_url, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
```

- [ ] **Step 3: Write main.py**

```python
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
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/config.py backend/app/database.py backend/app/main.py
git commit -m "feat: config, database engine, and FastAPI app shell"
```

---

## Task 3: Database Models

**Files:**
- Create: `backend/app/models/__init__.py`
- Create: `backend/app/models/group.py`
- Create: `backend/app/models/message.py`
- Create: `backend/app/models/slice.py`
- Create: `backend/app/models/topic.py`
- Create: `backend/app/models/term.py`
- Create: `backend/app/models/sync_job.py`

- [ ] **Step 1: Write group.py**

```python
# backend/app/models/group.py
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str | None] = mapped_column(String)
    type: Mapped[str | None] = mapped_column(String)  # group / channel / supergroup
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    messages: Mapped[list["Message"]] = relationship(back_populates="group")
    sync_jobs: Mapped[list["SyncJob"]] = relationship(back_populates="group")
```

- [ ] **Step 2: Write message.py**

```python
# backend/app/models/message.py
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    group_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("groups.id"), primary_key=True
    )
    sender_id: Mapped[int | None] = mapped_column(BigInteger)
    text: Mapped[str | None] = mapped_column(Text)
    reply_to_id: Mapped[int | None] = mapped_column(BigInteger)
    reply_to_group_id: Mapped[int | None] = mapped_column(BigInteger)
    message_type: Mapped[str] = mapped_column(String, default="text")
    raw_json: Mapped[dict | None] = mapped_column(JSONB)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    group: Mapped["Group"] = relationship(back_populates="messages")
```

- [ ] **Step 3: Write slice.py**

```python
# backend/app/models/slice.py
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Slice(Base):
    __tablename__ = "slices"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    group_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("groups.id"))
    time_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    time_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="pending")
    pg_done: Mapped[bool] = mapped_column(Boolean, default=False)
    qdrant_done: Mapped[bool] = mapped_column(Boolean, default=False)
    llm_done: Mapped[bool] = mapped_column(Boolean, default=False)
    embedding_model: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )

    messages: Mapped[list["SliceMessage"]] = relationship(back_populates="slice")
    topic_link: Mapped["SliceTopic | None"] = relationship(back_populates="slice")


class SliceMessage(Base):
    __tablename__ = "slice_messages"

    slice_id: Mapped[UUID] = mapped_column(ForeignKey("slices.id"), primary_key=True)
    message_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    group_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    position: Mapped[int] = mapped_column(Integer)

    slice: Mapped["Slice"] = relationship(back_populates="messages")
```

- [ ] **Step 4: Write topic.py**

```python
# backend/app/models/topic.py
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Topic(Base):
    __tablename__ = "topics"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    group_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("groups.id"))
    name: Mapped[str | None] = mapped_column(String(64))
    summary: Mapped[str | None] = mapped_column(Text)
    summary_version: Mapped[int] = mapped_column(Integer, default=0)
    llm_model: Mapped[str | None] = mapped_column(String)
    time_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    time_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    slice_count: Mapped[int] = mapped_column(Integer, default=0)

    slices: Mapped[list["SliceTopic"]] = relationship(back_populates="topic")


class SliceTopic(Base):
    __tablename__ = "slice_topics"

    slice_id: Mapped[UUID] = mapped_column(
        ForeignKey("slices.id"), primary_key=True, unique=True
    )
    topic_id: Mapped[UUID] = mapped_column(ForeignKey("topics.id"), primary_key=True)
    similarity: Mapped[float | None] = mapped_column(Float)

    slice: Mapped["Slice"] = relationship(back_populates="topic_link")
    topic: Mapped["Topic"] = relationship(back_populates="slices")
```

- [ ] **Step 5: Write term.py**

```python
# backend/app/models/term.py
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Term(Base):
    __tablename__ = "terms"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    word: Mapped[str] = mapped_column(String, nullable=False)
    variants: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    meanings: Mapped[list | None] = mapped_column(JSONB)  # [{meaning, confidence}]
    examples: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    status: Mapped[str] = mapped_column(String, default="auto")  # auto/confirmed/rejected
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    group_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("groups.id"))
    llm_model: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
```

- [ ] **Step 6: Write sync_job.py**

```python
# backend/app/models/sync_job.py
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SyncJob(Base):
    __tablename__ = "sync_jobs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    group_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("groups.id"))
    from_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    to_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String, default="pending")
    checkpoint_message_id: Mapped[int | None] = mapped_column(BigInteger)
    checkpoint_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )

    group: Mapped["Group"] = relationship(back_populates="sync_jobs")


class QaSession(Base):
    __tablename__ = "qa_sessions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str | None] = mapped_column(Text)
    group_id: Mapped[int | None] = mapped_column(BigInteger)
    llm_model: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )

    context: Mapped[list["QaContext"]] = relationship(back_populates="session")


class QaContext(Base):
    __tablename__ = "qa_context"

    qa_session_id: Mapped[UUID] = mapped_column(
        ForeignKey("qa_sessions.id"), primary_key=True
    )
    slice_id: Mapped[UUID] = mapped_column(ForeignKey("slices.id"), primary_key=True)
    similarity: Mapped[float | None] = mapped_column(Float)
    rank: Mapped[int | None] = mapped_column(Integer)

    session: Mapped["QaSession"] = relationship(back_populates="context")
```

- [ ] **Step 7: Write models/__init__.py**

```python
# backend/app/models/__init__.py
from app.models.group import Group
from app.models.message import Message
from app.models.slice import Slice, SliceMessage
from app.models.sync_job import QaContext, QaSession, SyncJob
from app.models.term import Term
from app.models.topic import SliceTopic, Topic

__all__ = [
    "Group", "Message",
    "Slice", "SliceMessage",
    "Topic", "SliceTopic",
    "Term",
    "SyncJob", "QaSession", "QaContext",
]
```

- [ ] **Step 8: Commit**

```bash
git add backend/app/models/
git commit -m "feat: SQLAlchemy ORM models for all tables"
```

---

## Task 4: Alembic Migration

**Files:**
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/versions/001_initial_schema.py`

- [ ] **Step 1: Initialize Alembic inside backend container**

```bash
docker compose run --rm backend bash -c "cd /app && alembic init alembic"
```

- [ ] **Step 2: Update alembic.ini sqlalchemy.url**

In `backend/alembic.ini`, set:
```ini
sqlalchemy.url = postgresql+asyncpg://threadgraph:threadgraph@postgres:5432/threadgraph
```

- [ ] **Step 3: Update alembic/env.py for async + models**

Replace the contents of `backend/alembic/env.py`:

```python
import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from app.database import Base
import app.models  # noqa: F401 — ensures all models are registered

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 4: Generate and run initial migration**

```bash
docker compose run --rm backend bash -c "alembic revision --autogenerate -m 'initial schema'"
docker compose run --rm backend bash -c "alembic upgrade head"
```

- [ ] **Step 5: Verify tables exist**

```bash
docker compose exec postgres psql -U threadgraph -c "\dt"
```

Expected: tables `groups`, `messages`, `slices`, `slice_messages`, `topics`, `slice_topics`, `terms`, `sync_jobs`, `qa_sessions`, `qa_context`.

- [ ] **Step 6: Add GIN index for full-text search on messages**

Add to the migration file (after the autogenerated code):

```python
from alembic import op
import sqlalchemy as sa

def upgrade() -> None:
    # ... autogenerated DDL above ...
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_messages_text_fts "
        "ON messages USING GIN (to_tsvector('simple', coalesce(text, '')))"
    )
    op.execute(
        "CREATE EXTENSION IF NOT EXISTS pg_trgm"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_terms_word_trgm "
        "ON terms USING GIN (word gin_trgm_ops)"
    )
```

Re-run:
```bash
docker compose run --rm backend bash -c "alembic upgrade head"
```

- [ ] **Step 7: Commit**

```bash
git add backend/alembic/ backend/alembic.ini
git commit -m "feat: alembic migrations with initial schema and FTS indexes"
```

---

## Task 5: Qdrant Client + Collection Init

**Files:**
- Create: `backend/app/qdrant_client.py`

- [ ] **Step 1: Write qdrant_client.py**

```python
# backend/app/qdrant_client.py
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, VectorParams

from app.config import settings

_client: AsyncQdrantClient | None = None

SLICES_COLLECTION = "slices"


async def get_qdrant() -> AsyncQdrantClient:
    global _client
    if _client is None:
        _client = AsyncQdrantClient(
            host=settings.qdrant_host, port=settings.qdrant_port
        )
    return _client


async def init_collections() -> None:
    client = await get_qdrant()
    existing = {c.name for c in (await client.get_collections()).collections}
    if SLICES_COLLECTION not in existing:
        await client.create_collection(
            collection_name=SLICES_COLLECTION,
            vectors_config=VectorParams(
                size=settings.embedding_dim, distance=Distance.COSINE
            ),
        )
```

- [ ] **Step 2: Call init_collections in lifespan**

Edit `backend/app/main.py`:

```python
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
```

- [ ] **Step 3: Start backend and verify Qdrant collection created**

```bash
docker compose up backend -d
curl http://localhost:8000/health
```

Expected: `{"status":"ok"}`

```bash
curl http://localhost:6333/collections/slices
```

Expected: JSON with `"status":"ok"` and vector size matching `EMBEDDING_DIM`.

- [ ] **Step 4: Commit**

```bash
git add backend/app/qdrant_client.py backend/app/main.py
git commit -m "feat: qdrant client with slices collection auto-init"
```

---

## Task 6: Telegram Auth API

**Files:**
- Create: `backend/app/ingestion/telegram_client.py`
- Create: `backend/app/api/auth.py`

- [ ] **Step 1: Write telegram_client.py**

```python
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
```

- [ ] **Step 2: Write api/auth.py**

```python
# backend/app/api/auth.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.ingestion.telegram_client import is_authorized, send_code, sign_in

router = APIRouter()


class SendCodeRequest(BaseModel):
    phone: str


class VerifyRequest(BaseModel):
    code: str
    password: str | None = None


@router.get("/status")
async def auth_status():
    authorized = await is_authorized()
    return {"authorized": authorized}


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
```

- [ ] **Step 3: Test auth status endpoint**

```bash
curl http://localhost:8000/auth/status
```

Expected: `{"authorized": false}` (before login)

- [ ] **Step 4: Commit**

```bash
git add backend/app/ingestion/telegram_client.py backend/app/api/auth.py
git commit -m "feat: telegram auth flow (send code, verify, session persistence)"
```

---

## Task 7: Real-Time Message Listener

**Files:**
- Create: `backend/app/ingestion/realtime_listener.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Write test for realtime_listener message saving**

```python
# backend/tests/test_realtime_listener.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone


@pytest.mark.asyncio
async def test_save_message_inserts_row(db_session):
    from app.ingestion.realtime_listener import save_message
    from app.models.message import Message

    mock_event = MagicMock()
    mock_event.message.id = 12345
    mock_event.message.peer_id.channel_id = 99
    mock_event.message.sender_id = 1
    mock_event.message.text = "hello world"
    mock_event.message.reply_to = None
    mock_event.message.media = None
    mock_event.message.date = datetime(2026, 1, 1, tzinfo=timezone.utc)
    mock_event.message.to_json = MagicMock(return_value='{}')

    await save_message(db_session, mock_event.message, group_id=99)

    result = await db_session.get(Message, (12345, 99))
    assert result is not None
    assert result.text == "hello world"
    assert result.group_id == 99
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker compose run --rm backend pytest tests/test_realtime_listener.py -v
```

Expected: `ImportError` or `AttributeError` — `save_message` doesn't exist yet.

- [ ] **Step 3: Write realtime_listener.py**

```python
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
        ts=message.date.replace(tzinfo=timezone.utc) if message.date else datetime.now(timezone.utc),
    ).on_conflict_do_nothing(index_elements=["id", "group_id"])

    await session.execute(stmt)
    await session.commit()


async def start_listener(client: TelegramClient) -> None:
    @client.on(events.NewMessage)
    async def handler(event):
        group_id = _get_group_id(event.message)
        if group_id is None:
            return
        async with AsyncSessionLocal() as session:
            await save_message(session, event.message, group_id)
            logger.info(f"Saved message {event.message.id} from group {group_id}")

    logger.info("Real-time listener started")
```

- [ ] **Step 4: Run test to verify it passes**

```bash
docker compose run --rm backend pytest tests/test_realtime_listener.py -v
```

Expected: PASS

- [ ] **Step 5: Wire listener into lifespan**

Edit `backend/app/main.py`:

```python
from contextlib import asynccontextmanager
import asyncio
import logging

from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.qdrant_client import init_collections

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_collections()
    from app.ingestion.telegram_client import get_client, is_authorized
    from app.ingestion.realtime_listener import start_listener

    client = await get_client()
    if await is_authorized():
        await start_listener(client)
        logger.info("Telegram listener started")
    else:
        logger.warning("Telegram not authorized — skipping listener. Use /auth/verify to log in.")
    yield


app = FastAPI(title="Thread Graph", lifespan=lifespan)
app.include_router(auth_router, prefix="/auth", tags=["auth"])


@app.get("/health")
async def health():
    return {"status": "ok"}
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/ingestion/realtime_listener.py backend/app/main.py backend/tests/test_realtime_listener.py
git commit -m "feat: real-time message listener with upsert-safe message saving"
```

---

## Task 8: Historical Sync Worker

**Files:**
- Create: `backend/app/ingestion/historical_sync.py`
- Create: `backend/tests/test_historical_sync.py`

- [ ] **Step 1: Write failing test**

```python
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
    mock_msg.peer_id = MagicMock()
    mock_msg.peer_id.channel_id = 42

    mock_client = AsyncMock()
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker compose run --rm backend pytest tests/test_historical_sync.py -v
```

Expected: ImportError — `run_sync_job` doesn't exist.

- [ ] **Step 3: Write historical_sync.py**

```python
# backend/app/ingestion/historical_sync.py
import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.ingestion.realtime_listener import save_message
from app.ingestion.telegram_client import get_client
from app.models.sync_job import SyncJob

logger = logging.getLogger(__name__)

BATCH_SIZE = 500
BATCH_SLEEP_SECONDS = 0.5  # Respect Telegram rate limits


async def run_sync_job(session: AsyncSession, job: SyncJob) -> None:
    job.status = "running"
    await session.commit()

    client = await get_client()

    try:
        count = 0
        async for message in client.iter_messages(
            job.group_id,
            offset_date=job.to_ts,
            reverse=True,
            limit=None,
        ):
            if job.from_ts and message.date < job.from_ts.replace(tzinfo=timezone.utc):
                break

            # Skip if before checkpoint
            if (
                job.checkpoint_message_id
                and message.id <= job.checkpoint_message_id
            ):
                continue

            await save_message(session, message, job.group_id)
            count += 1

            # Update checkpoint every BATCH_SIZE messages
            if count % BATCH_SIZE == 0:
                job.checkpoint_message_id = message.id
                job.checkpoint_ts = message.date
                await session.commit()
                await asyncio.sleep(BATCH_SLEEP_SECONDS)
                logger.info(f"SyncJob {job.id}: {count} messages synced, checkpoint={message.id}")

        job.status = "done"
        job.checkpoint_message_id = None
        await session.commit()
        logger.info(f"SyncJob {job.id} completed: {count} messages total")

    except Exception as e:
        job.status = "failed"
        job.error_message = str(e)
        await session.commit()
        logger.error(f"SyncJob {job.id} failed: {e}")
        raise


async def sync_worker_loop() -> None:
    """Background loop: picks up pending sync jobs and runs them."""
    logger.info("Historical sync worker started")
    while True:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(SyncJob)
                .where(SyncJob.status == "pending")
                .order_by(SyncJob.created_at)
                .limit(1)
            )
            job = result.scalar_one_or_none()

            if job:
                await run_sync_job(session, job)
            else:
                await asyncio.sleep(10)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
docker compose run --rm backend pytest tests/test_historical_sync.py -v
```

Expected: PASS

- [ ] **Step 5: Wire sync_worker_loop into lifespan**

Edit `backend/app/main.py` lifespan:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_collections()
    from app.ingestion.telegram_client import get_client, is_authorized
    from app.ingestion.realtime_listener import start_listener
    from app.ingestion.historical_sync import sync_worker_loop

    client = await get_client()
    if await is_authorized():
        await start_listener(client)
        logger.info("Telegram listener started")
    else:
        logger.warning("Telegram not authorized — use /auth/verify to log in.")

    asyncio.create_task(sync_worker_loop())
    yield
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/ingestion/historical_sync.py backend/tests/test_historical_sync.py backend/app/main.py
git commit -m "feat: historical sync worker with checkpoint-based resumption"
```

---

## Task 9: Groups + Sync API Endpoints

**Files:**
- Create: `backend/app/api/groups.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Write groups.py**

```python
# backend/app/api/groups.py
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.group import Group
from app.models.sync_job import SyncJob

router = APIRouter()


class GroupCreate(BaseModel):
    id: int
    name: str
    type: str = "group"


@router.get("/")
async def list_groups(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Group).where(Group.is_active == True))
    groups = result.scalars().all()
    return [
        {"id": g.id, "name": g.name, "type": g.type, "last_synced_at": g.last_synced_at}
        for g in groups
    ]


@router.post("/")
async def add_group(req: GroupCreate, db: AsyncSession = Depends(get_db)):
    group = Group(id=req.id, name=req.name, type=req.type, is_active=True)
    db.add(group)

    # Trigger initial 30-day sync
    job = SyncJob(
        id=uuid4(),
        group_id=req.id,
        from_ts=datetime.now(timezone.utc) - timedelta(days=30),
        to_ts=datetime.now(timezone.utc),
        status="pending",
    )
    db.add(job)
    await db.commit()
    return {"id": group.id, "name": group.name, "sync_job_id": str(job.id)}


@router.delete("/{group_id}")
async def remove_group(group_id: int, db: AsyncSession = Depends(get_db)):
    group = await db.get(Group, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    group.is_active = False
    await db.commit()
    return {"status": "deactivated"}


@router.post("/{group_id}/sync")
async def trigger_sync(
    group_id: int,
    from_days: int = 30,
    db: AsyncSession = Depends(get_db),
):
    group = await db.get(Group, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    job = SyncJob(
        id=uuid4(),
        group_id=group_id,
        from_ts=datetime.now(timezone.utc) - timedelta(days=from_days),
        to_ts=datetime.now(timezone.utc),
        status="pending",
    )
    db.add(job)
    await db.commit()
    return {"sync_job_id": str(job.id), "status": "pending"}


@router.get("/sync_jobs")
async def list_sync_jobs(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(SyncJob).order_by(SyncJob.created_at.desc()).limit(50)
    )
    jobs = result.scalars().all()
    return [
        {
            "id": str(j.id),
            "group_id": j.group_id,
            "status": j.status,
            "from_ts": j.from_ts,
            "to_ts": j.to_ts,
            "checkpoint_message_id": j.checkpoint_message_id,
            "error_message": j.error_message,
        }
        for j in jobs
    ]
```

- [ ] **Step 2: Register router in main.py**

```python
from app.api.groups import router as groups_router
app.include_router(groups_router, prefix="/groups", tags=["groups"])
```

- [ ] **Step 3: Verify endpoints**

```bash
curl http://localhost:8000/groups/
```

Expected: `[]` (empty list)

```bash
curl -X POST http://localhost:8000/groups/ \
  -H "Content-Type: application/json" \
  -d '{"id": 1234567, "name": "My Group", "type": "group"}'
```

Expected: `{"id": 1234567, "name": "My Group", "sync_job_id": "..."}`

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/groups.py backend/app/main.py
git commit -m "feat: groups CRUD and sync job trigger endpoints"
```

---

## Task 10: Test Fixtures + conftest

**Files:**
- Create: `backend/tests/conftest.py`

- [ ] **Step 1: Write conftest.py**

```python
# backend/tests/conftest.py
import asyncio
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base

TEST_DATABASE_URL = "postgresql+asyncpg://threadgraph:threadgraph@postgres:5432/threadgraph_test"


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def db_session():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()
```

- [ ] **Step 2: Create test DB and run all tests**

```bash
docker compose exec postgres createdb -U threadgraph threadgraph_test 2>/dev/null || true
docker compose run --rm backend pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/conftest.py
git commit -m "test: shared pytest fixtures with isolated test database"
```

---

## Task 11: Plan 1 Verification

- [ ] **Step 1: Run full test suite**

```bash
docker compose run --rm backend pytest tests/ -v --tb=short
```

Expected: all tests pass.

- [ ] **Step 2: End-to-end smoke test**

```bash
# Health check
curl http://localhost:8000/health

# Auth status (should be false until Telegram login)
curl http://localhost:8000/auth/status

# List groups (empty)
curl http://localhost:8000/groups/

# Qdrant slices collection exists
curl http://localhost:6333/collections/slices
```

All expected to return 200 with valid JSON.

- [ ] **Step 3: Final commit**

```bash
git add .
git commit -m "chore: plan 1 complete — infra, models, telegram ingestion, groups API"
```

---

---

## Task 12: Fixes — Missing Model + Cancel Endpoint

**Files:**
- Modify: `backend/app/models/message.py` — add `PendingSliceMessage`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/models/group.py` — add TYPE_CHECKING imports
- Modify: `backend/app/api/groups.py` — add cancel endpoint

- [ ] **Step 1: Add PendingSliceMessage to message.py**

Append to `backend/app/models/message.py`:

```python
class PendingSliceMessage(Base):
    __tablename__ = "pending_slice_messages"

    group_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("groups.id"), primary_key=True)
    message_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
```

- [ ] **Step 2: Export PendingSliceMessage from __init__.py**

Edit `backend/app/models/__init__.py`:

```python
from app.models.group import Group
from app.models.message import Message, PendingSliceMessage
from app.models.slice import Slice, SliceMessage
from app.models.sync_job import QaContext, QaSession, SyncJob
from app.models.term import Term
from app.models.topic import SliceTopic, Topic

__all__ = [
    "Group", "Message", "PendingSliceMessage",
    "Slice", "SliceMessage",
    "Topic", "SliceTopic",
    "Term",
    "SyncJob", "QaSession", "QaContext",
]
```

- [ ] **Step 3: Add TYPE_CHECKING imports to group.py**

Replace the top of `backend/app/models/group.py`:

```python
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.message import Message
    from app.models.sync_job import SyncJob
```

- [ ] **Step 4: Add cancel endpoint to groups.py**

Add to `backend/app/api/groups.py`:

```python
@router.post("/sync_jobs/{job_id}/cancel")
async def cancel_sync_job(job_id: str, db: AsyncSession = Depends(get_db)):
    from uuid import UUID
    job = await db.get(SyncJob, UUID(job_id))
    if not job:
        raise HTTPException(status_code=404, detail="SyncJob not found")
    if job.status not in ("pending", "running"):
        raise HTTPException(status_code=400, detail=f"Cannot cancel job in status: {job.status}")
    job.status = "failed"
    job.error_message = "Cancelled by user"
    await db.commit()
    return {"status": "cancelled"}
```

- [ ] **Step 5: Generate new migration for pending_slice_messages**

```bash
docker compose run --rm backend bash -c "alembic revision --autogenerate -m 'add pending_slice_messages'"
docker compose run --rm backend bash -c "alembic upgrade head"
```

- [ ] **Step 6: Run full test suite**

```bash
docker compose run --rm backend pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/ backend/app/api/groups.py backend/alembic/
git commit -m "fix: add pending_slice_messages model, cancel endpoint, TYPE_CHECKING imports"
```

---

## Next: Plan 2

Plan 2 will implement the processing pipeline:
- `backend/app/ingestion/pending_slice_manager.py` — delayed slice confirmation
- `backend/app/pipeline/slicer.py` — BFS + time window algorithm
- `backend/app/embedding.py` — OpenAI-compatible embedding client
- `backend/app/pipeline/clusterer.py` — Qdrant similarity clustering
- `backend/app/pipeline/summarizer.py` — incremental topic summarization (Claude)
- `backend/app/pipeline/jargon.py` — structured term extraction (Claude)
- `backend/app/worker/processor.py` — asyncio orchestration loop
