# backend/app/api/qa.py
from __future__ import annotations

import asyncio
import logging
from typing import Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from qdrant_client.models import FieldCondition, MatchValue
from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.embedding import get_embedding_client
from app.llm import create_sync_text_message, extract_text_content, get_llm_model, get_sync_anthropic_client
from app.models.message import Message
from app.models.slice import Slice, SliceMessage
from app.models.sync_job import QaContext, QaSession
from app.models.topic import SliceTopic
from app.qdrant_client import SLICES_COLLECTION, get_qdrant

logger = logging.getLogger(__name__)

router = APIRouter()


class QaRequest(BaseModel):
    question: str
    group_id: Optional[int] = None
    limit: int = 5


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def build_qa_prompt(question: str, contexts: list[dict]) -> str:
    parts = [f"请基于以下对话记录回答问题：\n\n问题：{question}\n\n相关对话片段：\n"]
    for i, ctx in enumerate(contexts, 1):
        msgs_text = "\n".join(f"[{m['ts']}] {m['text']}" for m in ctx["messages"])
        parts.append(f"片段{i} ({ctx['time_start']} - {ctx['time_end']}):\n{msgs_text}\n")
    parts.append("\n请用中文回答，并引用片段编号作为来源。如果信息不足，请明确说明。")
    return "".join(parts)


# ---------------------------------------------------------------------------
# POST /qa
# ---------------------------------------------------------------------------

@router.post("")
async def ask_question(
    req: QaRequest,
    db: AsyncSession = Depends(get_db),
):
    question: str = req.question
    group_id: Optional[int] = req.group_id
    limit: int = req.limit

    # 1. Generate embedding
    embedding_client = get_embedding_client()
    vectors = await embedding_client.embed([question])
    query_vector = vectors[0]

    # 2. Search Qdrant
    qdrant = await get_qdrant()
    search_filter = None
    if group_id is not None:
        from qdrant_client.models import Filter
        search_filter = Filter(
            must=[FieldCondition(key="group_id", match=MatchValue(value=group_id))]
        )

    hits = await qdrant.search(
        collection_name=SLICES_COLLECTION,
        query_vector=query_vector,
        query_filter=search_filter,
        score_threshold=0.5,
        limit=limit,
    )

    # 3. No results
    if not hits:
        return {"session_id": None, "answer": "没有找到相关内容", "sources": []}

    # 4. Load slice data for each hit
    contexts = []
    slice_infos = []  # (slice, score, topic_id)

    for hit in hits:
        slice_id = UUID(str(hit.id))
        score = hit.score

        # Load Slice from PG
        sl = await db.get(Slice, slice_id)
        if sl is None:
            continue

        # Load topic_id
        st_result = await db.execute(
            select(SliceTopic).where(SliceTopic.slice_id == slice_id)
        )
        st = st_result.scalar_one_or_none()
        topic_id = st.topic_id if st else None

        # Load SliceMessages ordered by position (up to 10)
        sm_result = await db.execute(
            select(SliceMessage)
            .where(SliceMessage.slice_id == slice_id)
            .order_by(SliceMessage.position)
            .limit(10)
        )
        slice_messages = sm_result.scalars().all()

        messages_out = []
        if slice_messages:
            pairs = [(sm.message_id, sm.group_id) for sm in slice_messages]
            msg_rows = (await db.execute(
                select(Message).where(tuple_(Message.id, Message.group_id).in_(pairs))
            )).scalars().all()
            msg_map = {(m.id, m.group_id): m for m in msg_rows}
            for sm in slice_messages:
                msg = msg_map.get((sm.message_id, sm.group_id))
                if msg is not None:
                    text = (msg.text or "")[:500]
                    messages_out.append({"ts": str(msg.ts), "text": text})

        contexts.append({
            "time_start": str(sl.time_start),
            "time_end": str(sl.time_end),
            "messages": messages_out,
        })
        slice_infos.append((sl, score, topic_id))

    # 5. Guard against empty contexts after PG load
    if not slice_infos:
        return {"session_id": None, "answer": "没有找到相关内容", "sources": []}

    # 6. Build prompt
    prompt = build_qa_prompt(question, contexts)

    # 7. Call Claude (sync wrapped in executor)
    client = get_sync_anthropic_client()
    llm_model = get_llm_model()
    response = await asyncio.get_running_loop().run_in_executor(
        None,
        lambda: create_sync_text_message(
            client,
            model=llm_model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        ),
    )
    answer_text = extract_text_content(response)

    # 8. Write QaSession + QaContext rows
    session = QaSession(
        id=uuid4(),
        question=question,
        answer=answer_text,
        group_id=group_id,
        llm_model=llm_model,
    )
    db.add(session)
    await db.flush()

    for rank, (sl, score, _topic_id) in enumerate(slice_infos):
        ctx_row = QaContext(
            qa_session_id=session.id,
            slice_id=sl.id,
            similarity=score,
            rank=rank,
        )
        db.add(ctx_row)

    await db.commit()

    # 9. Build response
    sources = []
    for sl, score, topic_id in slice_infos:
        sources.append({
            "slice_id": str(sl.id),
            "topic_id": str(topic_id) if topic_id else None,
            "similarity": score,
            "time_start": str(sl.time_start),
            "summary_preview": (sl.summary or "")[:100],
        })

    return {
        "session_id": str(session.id),
        "answer": answer_text,
        "sources": sources,
    }


# ---------------------------------------------------------------------------
# GET /qa/sessions
# ---------------------------------------------------------------------------

@router.get("/sessions")
async def list_sessions(
    limit: int = 20,
    offset: int = 0,
    group_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(QaSession)
    if group_id is not None:
        stmt = stmt.where(QaSession.group_id == group_id)
    stmt = stmt.order_by(QaSession.created_at.desc()).offset(offset).limit(limit)

    result = await db.execute(stmt)
    sessions = result.scalars().all()

    return [
        {
            "id": str(s.id),
            "question": s.question,
            "answer_preview": (s.answer or "")[:200],
            "group_id": s.group_id,
            "created_at": s.created_at,
        }
        for s in sessions
    ]
