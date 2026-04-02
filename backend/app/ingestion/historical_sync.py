# backend/app/ingestion/historical_sync.py
import asyncio
import logging

from telethon.tl.types import PeerChannel, PeerChat
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.ws import manager
from app.database import AsyncSessionLocal
from app.ingestion.realtime_listener import save_message
from app.ingestion.telegram_client import get_client
from app.models.group import Group
from app.models.sync_job import SyncJob

logger = logging.getLogger(__name__)

BATCH_SIZE = 500
BATCH_SLEEP_SECONDS = 0.5


async def _resolve_history_target(session: AsyncSession, group_id: int):
    group = await session.get(Group, group_id)
    if group is None:
        return group_id

    if group.type in {"channel", "supergroup"}:
        return PeerChannel(group_id)
    if group.type == "group":
        return PeerChat(group_id)
    return group_id


async def run_sync_job(session: AsyncSession, job: SyncJob) -> None:
    from app.worker.processor import confirm_ready_pending_slices

    job.status = "running"
    await session.commit()

    client = await get_client()
    history_target = await _resolve_history_target(session, job.group_id)

    try:
        count = 0
        async for message in client.iter_messages(
            history_target,
            offset_date=job.from_ts,
            reverse=True,
            limit=None,
        ):
            if job.to_ts and message.date > job.to_ts:
                break

            if (
                job.checkpoint_message_id
                and message.id <= job.checkpoint_message_id
            ):
                continue

            await save_message(session, message, job.group_id)
            count += 1

            if count % BATCH_SIZE == 0:
                job.checkpoint_message_id = message.id
                job.checkpoint_ts = message.date
                await session.commit()
                try:
                    await manager.broadcast(
                        event="sync_progress",
                        payload={
                            "job_id": str(job.id),
                            "group_id": job.group_id,
                            "checkpoint_message_id": job.checkpoint_message_id,
                            "status": job.status,
                        },
                        dedup_key=f"sync_{job.id}_{job.checkpoint_message_id}",
                    )
                except Exception:
                    pass
                await asyncio.sleep(BATCH_SLEEP_SECONDS)
                logger.info(f"SyncJob {job.id}: {count} messages synced")

        if count > 0:
            await confirm_ready_pending_slices(session)

        job.status = "done"
        job.checkpoint_message_id = None
        await session.commit()
        logger.info(f"SyncJob {job.id} completed: {count} messages")

    except Exception as e:
        job.status = "failed"
        job.error_message = str(e)
        await session.commit()
        logger.error(f"SyncJob {job.id} failed: {e}")
        raise


async def sync_worker_loop() -> None:
    """Background loop: picks up pending sync jobs."""
    logger.info("Historical sync worker started")
    while True:
        try:
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
        except Exception as e:
            logger.error(f"sync_worker_loop error: {e}", exc_info=True)
            await asyncio.sleep(10)
