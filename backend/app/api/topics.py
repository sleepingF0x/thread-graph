# backend/app/api/topics.py
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update, nullslast, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.group import Group
from app.models.message import Message
from app.models.slice import Slice, SliceMessage
from app.models.topic import SliceTopic, Topic

router = APIRouter()


# ---------------------------------------------------------------------------
# GET /groups/{group_id}/topics
# ---------------------------------------------------------------------------

@router.get("/groups/{group_id}/topics")
async def list_topics(
    group_id: int,
    limit: int = 50,
    offset: int = 0,
    from_ts: Optional[datetime] = None,
    to_ts: Optional[datetime] = None,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Topic).where(Topic.group_id == group_id)
    if from_ts is not None:
        stmt = stmt.where(Topic.time_end >= from_ts)
    if to_ts is not None:
        stmt = stmt.where(Topic.time_end <= to_ts)
    stmt = stmt.order_by(nullslast(Topic.time_end.desc())).offset(offset).limit(limit)

    result = await db.execute(stmt)
    topics = result.scalars().all()

    return [
        {
            "id": str(t.id),
            "name": t.name,
            "summary": t.summary,
            "is_active": t.is_active,
            "slice_count": t.slice_count,
            "time_start": t.time_start,
            "time_end": t.time_end,
        }
        for t in topics
    ]


# ---------------------------------------------------------------------------
# GET /groups/{group_id}/topics/{topic_id}
# ---------------------------------------------------------------------------

@router.get("/groups/{group_id}/topics/{topic_id}")
async def get_topic_detail(
    group_id: int,
    topic_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    # Load topic with slice_topics -> slice -> messages chain
    stmt = (
        select(Topic)
        .where(Topic.id == topic_id, Topic.group_id == group_id)
        .options(
            selectinload(Topic.slices)
            .selectinload(SliceTopic.slice)
            .selectinload(Slice.messages)
        )
    )
    result = await db.execute(stmt)
    topic = result.scalar_one_or_none()
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")

    # Collect all (message_id, group_id) pairs across all slices in one pass,
    # then fetch all messages in a single query (avoids N+1 per slice).
    slice_refs_map: dict = {}
    all_pairs: list[tuple[int, int]] = []
    for st in topic.slices:
        sl = st.slice
        refs = sorted(sl.messages, key=lambda m: m.position)
        slice_refs_map[sl.id] = (sl, refs)
        all_pairs.extend((r.message_id, r.group_id) for r in refs)

    msg_map: dict[tuple[int, int], Message] = {}
    if all_pairs:
        rows = (await db.execute(
            select(Message).where(tuple_(Message.id, Message.group_id).in_(all_pairs))
        )).scalars().all()
        msg_map = {(m.id, m.group_id): m for m in rows}

    slices_out = []
    for st in topic.slices:
        sl, refs = slice_refs_map[st.slice.id]
        messages_out = []
        for r in refs:
            msg = msg_map.get((r.message_id, r.group_id))
            if msg is not None:
                messages_out.append(
                    {
                        "id": r.message_id,
                        "text": msg.text,
                        "ts": msg.ts,
                        "sender_id": msg.sender_id,
                    }
                )
        slices_out.append(
            {
                "id": str(st.slice.id),
                "time_start": st.slice.time_start,
                "time_end": st.slice.time_end,
                "summary": st.slice.summary,
                "messages": messages_out,
            }
        )

    return {
        "id": str(topic.id),
        "name": topic.name,
        "summary": topic.summary,
        "is_active": topic.is_active,
        "slice_count": topic.slice_count,
        "time_start": topic.time_start,
        "time_end": topic.time_end,
        "slices": slices_out,
    }


# ---------------------------------------------------------------------------
# GET /topics/active  (must be declared BEFORE /topics/{topic_id}/reprocess)
# ---------------------------------------------------------------------------

@router.get("/topics/active")
async def list_active_topics(
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(Topic, Group.name.label("group_name"))
        .join(Group, Group.id == Topic.group_id)
        .where(Topic.is_active == True)  # noqa: E712
        .order_by(nullslast(Topic.time_end.desc()))
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.all()

    return [
        {
            "id": str(t.id),
            "name": t.name,
            "summary": t.summary,
            "group_id": t.group_id,
            "group_name": group_name,
            "slice_count": t.slice_count,
            "time_start": t.time_start,
            "time_end": t.time_end,
        }
        for t, group_name in rows
    ]


# ---------------------------------------------------------------------------
# POST /topics/{topic_id}/reprocess
# ---------------------------------------------------------------------------

@router.post("/topics/{topic_id}/reprocess")
async def reprocess_topic(
    topic_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    topic = await db.get(Topic, topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")

    # Find all slice IDs linked to this topic
    st_result = await db.execute(
        select(SliceTopic.slice_id).where(SliceTopic.topic_id == topic_id)
    )
    slice_ids = st_result.scalars().all()

    slices_reset = 0
    if slice_ids:
        await db.execute(
            update(Slice)
            .where(Slice.id.in_(slice_ids))
            .values(status="pending", pg_done=False, qdrant_done=False, llm_done=False)
        )
        slices_reset = len(slice_ids)

    # Reset topic metadata
    topic.summary = ""
    topic.summary_version = 0
    await db.commit()

    return {"topic_id": str(topic_id), "slices_reset": slices_reset}
