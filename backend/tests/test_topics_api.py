# backend/tests/test_topics_api.py
"""
Tests for the Topics API endpoints.

Uses httpx.AsyncClient with ASGITransport and app.dependency_overrides
to inject the async test db_session fixture — all running in the same
event loop so asyncpg connections stay valid.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.main import app
from app.models.group import Group
from app.models.message import Message
from app.models.slice import Slice, SliceMessage
from app.models.topic import SliceTopic, Topic


# ---------------------------------------------------------------------------
# Helper: async context manager for an overridden client
# ---------------------------------------------------------------------------

def make_override(db_session: AsyncSession):
    async def override_get_db():
        yield db_session
    return override_get_db


async def _aclient(db_session: AsyncSession) -> httpx.AsyncClient:
    app.dependency_overrides[get_db] = make_override(db_session)
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    )


# ---------------------------------------------------------------------------
# DB fixture helpers
# ---------------------------------------------------------------------------

async def _create_group(db: AsyncSession, group_id: int = 1001, name: str = "Test Group") -> Group:
    group = Group(id=group_id, name=name, type="group", is_active=True)
    db.add(group)
    await db.flush()
    return group


async def _create_topic(
    db: AsyncSession,
    group_id: int,
    *,
    name: str = "Topic A",
    is_active: bool = True,
    time_start: datetime | None = None,
    time_end: datetime | None = None,
    slice_count: int = 0,
    summary: str = "some summary",
    summary_version: int = 0,
) -> Topic:
    topic = Topic(
        id=uuid4(),
        group_id=group_id,
        name=name,
        summary=summary,
        summary_version=summary_version,
        is_active=is_active,
        slice_count=slice_count,
        time_start=time_start,
        time_end=time_end,
    )
    db.add(topic)
    await db.flush()
    return topic


async def _create_slice(
    db: AsyncSession,
    group_id: int,
    *,
    time_start: datetime | None = None,
    time_end: datetime | None = None,
    summary: str | None = "slice summary",
    status: str = "done",
    pg_done: bool = True,
    qdrant_done: bool = True,
    llm_done: bool = True,
) -> Slice:
    sl = Slice(
        id=uuid4(),
        group_id=group_id,
        time_start=time_start,
        time_end=time_end,
        summary=summary,
        status=status,
        pg_done=pg_done,
        qdrant_done=qdrant_done,
        llm_done=llm_done,
    )
    db.add(sl)
    await db.flush()
    return sl


async def _link_slice_topic(db: AsyncSession, slice_id, topic_id) -> SliceTopic:
    st = SliceTopic(slice_id=slice_id, topic_id=topic_id, similarity=0.9)
    db.add(st)
    await db.flush()
    return st


async def _create_message(
    db: AsyncSession,
    message_id: int,
    group_id: int,
    *,
    text: str = "Hello",
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
    db: AsyncSession, slice_id, message_id: int, group_id: int, position: int = 0
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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_topics_empty(db_session: AsyncSession):
    """GET /groups/{group_id}/topics returns 200 with empty list when no topics exist."""
    await _create_group(db_session, group_id=2001)
    await db_session.commit()

    async with await _aclient(db_session) as client:
        resp = await client.get("/groups/2001/topics")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_topics_filtered(db_session: AsyncSession):
    """from_ts/to_ts filter correctly filters by time_end."""
    await _create_group(db_session, group_id=2002)

    early = datetime(2024, 1, 10, tzinfo=timezone.utc)
    late = datetime(2024, 3, 10, tzinfo=timezone.utc)

    await _create_topic(db_session, 2002, name="Early", time_end=early)
    await _create_topic(db_session, 2002, name="Late", time_end=late)
    await db_session.commit()

    async with await _aclient(db_session) as client:
        # Only topics with time_end >= Feb 1 → should get "Late"
        resp = await client.get(
            "/groups/2002/topics", params={"from_ts": "2024-02-01T00:00:00Z"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "Late"

        # Only topics with time_end <= Feb 1 → should get "Early"
        resp2 = await client.get(
            "/groups/2002/topics", params={"to_ts": "2024-02-01T00:00:00Z"}
        )
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert len(data2) == 1
        assert data2[0]["name"] == "Early"


@pytest.mark.asyncio
async def test_get_topic_detail(db_session: AsyncSession):
    """Returns topic with slices and messages (create test data)."""
    await _create_group(db_session, group_id=2003)

    topic = await _create_topic(db_session, 2003, name="Detail Topic", slice_count=1)
    sl = await _create_slice(db_session, 2003, summary="a slice")
    await _link_slice_topic(db_session, sl.id, topic.id)
    await _create_message(db_session, 9001, 2003, text="First message", sender_id=11)
    await _link_message_to_slice(db_session, sl.id, 9001, 2003, position=0)
    await db_session.commit()

    async with await _aclient(db_session) as client:
        resp = await client.get(f"/groups/2003/topics/{topic.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == str(topic.id)
    assert data["name"] == "Detail Topic"
    assert len(data["slices"]) == 1
    slc = data["slices"][0]
    assert slc["id"] == str(sl.id)
    assert len(slc["messages"]) == 1
    assert slc["messages"][0]["text"] == "First message"
    assert slc["messages"][0]["sender_id"] == 11


@pytest.mark.asyncio
async def test_get_active_topics(db_session: AsyncSession):
    """Only is_active=True topics are returned, with group_name."""
    await _create_group(db_session, group_id=2004, name="Active Group")

    await _create_topic(db_session, 2004, name="Active Topic", is_active=True)
    await _create_topic(db_session, 2004, name="Inactive Topic", is_active=False)
    await db_session.commit()

    async with await _aclient(db_session) as client:
        resp = await client.get("/topics/active")
    assert resp.status_code == 200
    data = resp.json()

    names = [t["name"] for t in data]
    assert "Active Topic" in names
    assert "Inactive Topic" not in names

    active = next(t for t in data if t["name"] == "Active Topic")
    assert active["group_name"] == "Active Group"
    assert active["group_id"] == 2004


@pytest.mark.asyncio
async def test_reprocess_topic(db_session: AsyncSession):
    """Resets slice statuses and topic.summary/summary_version."""
    from sqlalchemy import select as sa_select

    await _create_group(db_session, group_id=2005)

    topic = await _create_topic(
        db_session, 2005, name="Reprocess Me", slice_count=2,
        summary="old summary", summary_version=3,
    )

    sl1 = await _create_slice(db_session, 2005, status="done", pg_done=True, qdrant_done=True, llm_done=True)
    sl2 = await _create_slice(db_session, 2005, status="done", pg_done=True, qdrant_done=True, llm_done=True)
    await _link_slice_topic(db_session, sl1.id, topic.id)
    await _link_slice_topic(db_session, sl2.id, topic.id)
    await db_session.commit()

    async with await _aclient(db_session) as client:
        resp = await client.post(f"/topics/{topic.id}/reprocess")
    assert resp.status_code == 200
    data = resp.json()
    assert data["topic_id"] == str(topic.id)
    assert data["slices_reset"] == 2

    # Verify DB state
    await db_session.refresh(topic)
    assert topic.summary == ""
    assert topic.summary_version == 0

    result = await db_session.execute(
        sa_select(Slice).where(Slice.id.in_([sl1.id, sl2.id]))
    )
    slices = result.scalars().all()
    for s in slices:
        assert s.status == "pending"
        assert s.pg_done is False
        assert s.qdrant_done is False
        assert s.llm_done is False


@pytest.mark.asyncio
async def test_reprocess_topic_not_found(db_session: AsyncSession):
    """Returns 404 when topic does not exist."""
    async with await _aclient(db_session) as client:
        fake_id = str(uuid4())
        resp = await client.post(f"/topics/{fake_id}/reprocess")
    assert resp.status_code == 404
