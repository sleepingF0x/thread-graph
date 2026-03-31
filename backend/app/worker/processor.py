# backend/app/worker/processor.py
"""
Processing worker: polls for work and runs the full pipeline.

Two loops:
1. pending_slice_loop: every 5 min, confirms ready pending_slice_messages into slices
2. pipeline_loop: continuously processes slices with status='pending'

Pipeline per slice:
  messages → embedding → Qdrant upsert → find similar topic → assign/create topic
  → summarize slice → update topic summary → extract jargon → mark done
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

PENDING_CHECK_INTERVAL = 300   # 5 minutes
PIPELINE_SLEEP = 5             # seconds between pipeline polls
SILENCE_WINDOW = timedelta(minutes=30)


# ── Pending slice confirmation ────────────────────────────────────────────────

async def confirm_ready_pending_slices(session: AsyncSession) -> int:
    """Convert pending_slice_messages that are 'done talking' into confirmed slices.
    Returns number of slices created."""
    from app.models.message import PendingSliceMessage, Message
    from app.models.slice import Slice, SliceMessage
    from app.pipeline.slicer import slice_messages

    cutoff = datetime.now(timezone.utc) - SILENCE_WINDOW

    result = await session.execute(
        select(PendingSliceMessage).where(PendingSliceMessage.ts <= cutoff)
    )
    pending = result.scalars().all()
    if not pending:
        return 0

    by_group: dict[int, list] = {}
    for p in pending:
        by_group.setdefault(p.group_id, []).append(p)

    created = 0
    for group_id, pending_rows in by_group.items():
        msg_ids = [p.message_id for p in pending_rows]
        msg_result = await session.execute(
            select(Message).where(
                Message.group_id == group_id,
                Message.id.in_(msg_ids),
            )
        )
        messages = msg_result.scalars().all()

        slices = slice_messages(messages)

        for slice_msgs in slices:
            if not slice_msgs:
                continue
            ts_list = [m.ts for m in slice_msgs]
            new_slice = Slice(
                id=uuid4(),
                group_id=group_id,
                time_start=min(ts_list),
                time_end=max(ts_list),
                status="pending",
            )
            session.add(new_slice)
            await session.flush()

            for pos, msg in enumerate(sorted(slice_msgs, key=lambda m: m.ts)):
                session.add(SliceMessage(
                    slice_id=new_slice.id,
                    message_id=msg.id,
                    group_id=group_id,
                    position=pos,
                ))
            created += 1

        for p in pending_rows:
            await session.delete(p)

    await session.commit()
    logger.info(f"Confirmed {created} slices from pending messages")
    return created


async def pending_slice_loop() -> None:
    logger.info("Pending slice loop started")
    while True:
        try:
            async with AsyncSessionLocal() as session:
                await confirm_ready_pending_slices(session)
        except Exception as e:
            logger.error(f"pending_slice_loop error: {e}")
        await asyncio.sleep(PENDING_CHECK_INTERVAL)


# ── Pipeline: process confirmed slices ───────────────────────────────────────

async def process_slice(session: AsyncSession, slice_obj) -> None:
    """Run the full pipeline on one slice."""
    import anthropic
    from app.config import settings
    from app.embedding import get_embedding_client
    from app.qdrant_client import get_qdrant
    from app.pipeline.clusterer import find_similar_topic, upsert_slice_embedding
    from app.pipeline.summarizer import summarize_slice, update_topic_summary, generate_topic_name
    from app.pipeline.jargon import extract_terms, build_system_context
    from app.models.message import Message
    from app.models.slice import SliceMessage
    from app.models.topic import Topic, SliceTopic
    from app.models.term import Term

    result = await session.execute(
        select(SliceMessage)
        .where(SliceMessage.slice_id == slice_obj.id)
        .order_by(SliceMessage.position)
    )
    slice_messages_rows = result.scalars().all()

    if not slice_messages_rows:
        slice_obj.status = "processed"
        await session.commit()
        return

    msg_ids = [sm.message_id for sm in slice_messages_rows]
    msg_result = await session.execute(
        select(Message).where(
            Message.group_id == slice_obj.group_id,
            Message.id.in_(msg_ids),
        )
    )
    messages = msg_result.scalars().all()
    texts = [m.text or "" for m in messages if m.text]

    if not texts:
        slice_obj.status = "processed"
        await session.commit()
        return

    # Load confirmed terms for context injection
    term_result = await session.execute(
        select(Term).where(
            Term.status == "confirmed",
            (Term.group_id == slice_obj.group_id) | (Term.group_id.is_(None)),
        ).limit(50)
    )
    confirmed_terms = [
        {"word": t.word, "meanings": t.meanings or []}
        for t in term_result.scalars().all()
    ]
    term_context = build_system_context(confirmed_terms)

    # 1. Generate slice summary
    claude = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    slice_summary = await summarize_slice(claude, texts)
    slice_obj.summary = slice_summary
    slice_obj.llm_done = True
    await session.commit()

    # 2. Generate embedding
    embedder = get_embedding_client()
    summary_with_context = f"{term_context}\n\n{slice_summary}" if term_context else slice_summary
    embeddings = await embedder.embed([summary_with_context])
    embedding = embeddings[0]
    slice_obj.embedding_model = settings.embedding_model
    slice_obj.pg_done = True
    await session.commit()

    # 3. Upsert to Qdrant + find similar topic
    qdrant = await get_qdrant()
    topic_id_str = await find_similar_topic(qdrant, slice_obj.group_id, embedding)

    topic = None
    if topic_id_str:
        from uuid import UUID as UUIDType
        topic = await session.get(Topic, UUIDType(topic_id_str))

    if topic is None:
        topic_name = await generate_topic_name(claude, slice_summary)
        topic = Topic(
            id=uuid4(),
            group_id=slice_obj.group_id,
            name=topic_name,
            summary=None,
            is_active=True,
            slice_count=0,
        )
        session.add(topic)
        await session.flush()

    # 4. Incremental topic summary update
    new_summary = await update_topic_summary(
        claude,
        topic_name=topic.name or "",
        current_summary=topic.summary,
        new_slice_summary=slice_summary,
    )
    topic.summary = new_summary
    topic.summary_version += 1
    topic.slice_count += 1
    topic.llm_model = "claude-sonnet-4-6"
    topic.time_end = slice_obj.time_end
    if topic.time_start is None:
        topic.time_start = slice_obj.time_start

    # 5. Link slice → topic
    session.add(SliceTopic(
        slice_id=slice_obj.id,
        topic_id=topic.id,
        similarity=None,
    ))

    # 6. Upsert embedding with topic_id in payload
    await upsert_slice_embedding(
        qdrant,
        slice_id=slice_obj.id,
        embedding=embedding,
        payload={
            "group_id": slice_obj.group_id,
            "time_start": slice_obj.time_start.isoformat() if slice_obj.time_start else None,
            "time_end": slice_obj.time_end.isoformat() if slice_obj.time_end else None,
            "topic_id": str(topic.id),
            "summary_preview": slice_summary[:100],
        },
    )
    slice_obj.qdrant_done = True

    # 7. Extract jargon
    new_terms = await extract_terms(claude, texts, slice_obj.group_id)
    for term_data in new_terms:
        existing = await session.execute(
            select(Term).where(
                Term.word == term_data["word"],
                Term.group_id == term_data["group_id"],
            )
        )
        if existing.scalar_one_or_none() is None:
            session.add(Term(
                id=uuid4(),
                word=term_data["word"],
                meanings=term_data["meanings"],
                examples=term_data["examples"],
                status="auto",
                needs_review=term_data["needs_review"],
                group_id=term_data["group_id"],
                llm_model="claude-sonnet-4-6",
            ))

    slice_obj.status = "processed"
    await session.commit()
    logger.info(f"Processed slice {slice_obj.id} → topic '{topic.name}'")


async def pipeline_loop() -> None:
    logger.info("Pipeline loop started")
    while True:
        try:
            from app.models.slice import Slice
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(Slice)
                    .where(Slice.status == "pending")
                    .order_by(Slice.created_at)
                    .limit(1)
                )
                slice_obj = result.scalar_one_or_none()

                if slice_obj:
                    await process_slice(session, slice_obj)
                else:
                    await asyncio.sleep(PIPELINE_SLEEP)

        except Exception as e:
            logger.error(f"pipeline_loop error: {e}", exc_info=True)
            await asyncio.sleep(PIPELINE_SLEEP)
