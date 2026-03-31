# backend/app/ingestion/historical_sync.py
import asyncio
import logging
from datetime import timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.ingestion.realtime_listener import save_message
from app.ingestion.telegram_client import get_client
from app.models.sync_job import SyncJob

logger = logging.getLogger(__name__)

BATCH_SIZE = 500
BATCH_SLEEP_SECONDS = 0.5


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
                await asyncio.sleep(BATCH_SLEEP_SECONDS)
                logger.info(f"SyncJob {job.id}: {count} messages synced")

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
