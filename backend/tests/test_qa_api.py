# backend/tests/test_qa_api.py
"""
Tests for the QA/RAG API endpoints.

Uses httpx.AsyncClient with ASGITransport and app.dependency_overrides
to inject the async test db_session fixture.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.main import app
from app.models.group import Group
from app.models.message import Message
from app.models.slice import Slice, SliceMessage
from app.models.sync_job import QaContext, QaSession


# ---------------------------------------------------------------------------
# Helper: async context manager for an overridden client
# ---------------------------------------------------------------------------

def make_override(db_session: AsyncSession):
    async def override_get_db():
        yield db_session
    return override_get_db


@asynccontextmanager
async def _aclient(db_session: AsyncSession):
    app.dependency_overrides[get_db] = make_override(db_session)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        try:
            yield client
        finally:
            app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# DB fixture helpers
# ---------------------------------------------------------------------------

async def _create_group(db: AsyncSession, group_id: int = 5001, name: str = "QA Test Group") -> Group:
    group = Group(id=group_id, name=name, type="group", is_active=True)
    db.add(group)
    await db.flush()
    return group


async def _create_slice(
    db: AsyncSession,
    group_id: int,
    *,
    summary: str = "Test slice summary",
) -> Slice:
    sl = Slice(
        id=uuid4(),
        group_id=group_id,
        time_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
        time_end=datetime(2024, 1, 2, tzinfo=timezone.utc),
        summary=summary,
        status="done",
        pg_done=True,
        qdrant_done=True,
        llm_done=True,
    )
    db.add(sl)
    await db.flush()
    return sl


async def _create_message(
    db: AsyncSession,
    message_id: int,
    group_id: int,
    *,
    text: str = "Hello test",
    sender_id: int = 42,
    ts: datetime | None = None,
) -> Message:
    msg = Message(
        id=message_id,
        group_id=group_id,
        text=text,
        sender_id=sender_id,
        ts=ts or datetime(2024, 1, 1, tzinfo=timezone.utc),
        message_type="text",
    )
    db.add(msg)
    await db.flush()
    return msg


async def _link_message_to_slice(
    db: AsyncSession,
    slice_id,
    message_id: int,
    group_id: int,
    position: int = 0,
) -> SliceMessage:
    sm = SliceMessage(
        slice_id=slice_id,
        message_id=message_id,
        group_id=group_id,
        position=position,
    )
    db.add(sm)
    await db.flush()
    return sm


def _make_qdrant_hit(slice_id, score: float = 0.85, group_id: int = 5001):
    hit = MagicMock()
    hit.id = str(slice_id)
    hit.score = score
    hit.payload = {"group_id": group_id, "topic_id": None, "summary_preview": "test preview"}
    return hit


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_qa_no_results(db_session: AsyncSession):
    """POST /qa with no Qdrant results returns no-results response."""
    mock_embed_client = MagicMock()
    mock_embed_client.embed = AsyncMock(return_value=[[0.1] * 1536])

    mock_qdrant = AsyncMock()
    mock_qdrant.search = AsyncMock(return_value=[])

    with patch("app.api.qa.get_embedding_client", return_value=mock_embed_client), \
         patch("app.api.qa.get_qdrant", new=AsyncMock(return_value=mock_qdrant)):
        async with _aclient(db_session) as client:
            resp = await client.post("/qa", json={"question": "test?"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["answer"] == "没有找到相关内容"
    assert data["sources"] == []
    assert data["session_id"] is None


@pytest.mark.asyncio
async def test_qa_with_results(db_session: AsyncSession):
    """POST /qa with Qdrant results returns answer and sources."""
    await _create_group(db_session, group_id=5001)
    sl = await _create_slice(db_session, 5001, summary="test slice summary")
    await _create_message(db_session, 8001, 5001, text="Test message content")
    await _link_message_to_slice(db_session, sl.id, 8001, 5001, position=0)
    await db_session.commit()

    mock_embed_client = MagicMock()
    mock_embed_client.embed = AsyncMock(return_value=[[0.1] * 1536])

    mock_qdrant = AsyncMock()
    mock_qdrant.search = AsyncMock(return_value=[_make_qdrant_hit(sl.id, score=0.85)])

    mock_anthropic_response = MagicMock()
    mock_anthropic_response.content = [MagicMock(text="答案：这是测试答案")]

    mock_anthropic_client = MagicMock()
    mock_anthropic_client.messages.create = MagicMock(return_value=mock_anthropic_response)

    with patch("app.api.qa.get_embedding_client", return_value=mock_embed_client), \
         patch("app.api.qa.get_qdrant", new=AsyncMock(return_value=mock_qdrant)), \
         patch("app.api.qa.get_sync_anthropic_client", return_value=mock_anthropic_client):
        async with _aclient(db_session) as client:
            resp = await client.post("/qa", json={"question": "What happened?"})

    assert resp.status_code == 200
    data = resp.json()
    assert "答案" in data["answer"]
    assert len(data["sources"]) == 1
    assert data["session_id"] is not None
    src = data["sources"][0]
    assert src["slice_id"] == str(sl.id)
    assert src["similarity"] == 0.85


@pytest.mark.asyncio
async def test_qa_writes_session(db_session: AsyncSession):
    """POST /qa writes QaSession and QaContext rows to DB."""
    await _create_group(db_session, group_id=5002)
    sl = await _create_slice(db_session, 5002, summary="session test summary")
    await _create_message(db_session, 8002, 5002, text="Session test message")
    await _link_message_to_slice(db_session, sl.id, 8002, 5002, position=0)
    await db_session.commit()

    mock_embed_client = MagicMock()
    mock_embed_client.embed = AsyncMock(return_value=[[0.1] * 1536])

    mock_qdrant = AsyncMock()
    mock_qdrant.search = AsyncMock(return_value=[_make_qdrant_hit(sl.id, score=0.75, group_id=5002)])

    mock_anthropic_response = MagicMock()
    mock_anthropic_response.content = [MagicMock(text="DB写入测试答案")]

    mock_anthropic_client = MagicMock()
    mock_anthropic_client.messages.create = MagicMock(return_value=mock_anthropic_response)

    with patch("app.api.qa.get_embedding_client", return_value=mock_embed_client), \
         patch("app.api.qa.get_qdrant", new=AsyncMock(return_value=mock_qdrant)), \
         patch("app.api.qa.get_sync_anthropic_client", return_value=mock_anthropic_client):
        async with _aclient(db_session) as client:
            resp = await client.post("/qa", json={"question": "DB test question"})

    assert resp.status_code == 200
    session_id = resp.json()["session_id"]

    # Verify QaSession was written
    result = await db_session.execute(select(QaSession))
    sessions = result.scalars().all()
    assert len(sessions) == 1
    assert sessions[0].question == "DB test question"
    assert str(sessions[0].id) == session_id

    # Verify QaContext was written
    ctx_result = await db_session.execute(select(QaContext))
    contexts = ctx_result.scalars().all()
    assert len(contexts) == 1
    assert contexts[0].slice_id == sl.id
    assert contexts[0].qa_session_id == sessions[0].id


@pytest.mark.asyncio
async def test_qa_missing_question(db_session: AsyncSession):
    """POST /qa without 'question' field returns 422."""
    async with _aclient(db_session) as client:
        resp = await client.post("/qa", json={})
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_sessions_empty(db_session: AsyncSession):
    """GET /qa/sessions returns 200 and empty list when no sessions exist."""
    async with _aclient(db_session) as client:
        resp = await client.get("/qa/sessions")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_sessions(db_session: AsyncSession):
    """GET /qa/sessions returns sessions with answer_preview truncated to 200 chars."""
    long_answer = "A" * 300
    session = QaSession(
        id=uuid4(),
        question="What is this?",
        answer=long_answer,
        group_id=None,
        llm_model="claude-sonnet-4-6",
    )
    db_session.add(session)
    await db_session.commit()

    async with _aclient(db_session) as client:
        resp = await client.get("/qa/sessions")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    item = data[0]
    assert item["question"] == "What is this?"
    assert len(item["answer_preview"]) == 200
    assert item["answer_preview"] == "A" * 200
    assert item["id"] == str(session.id)
