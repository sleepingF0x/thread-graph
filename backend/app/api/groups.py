# backend/app/api/groups.py
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

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


@router.post("/sync_jobs/{job_id}/cancel")
async def cancel_sync_job(job_id: str, db: AsyncSession = Depends(get_db)):
    job = await db.get(SyncJob, UUID(job_id))
    if not job:
        raise HTTPException(status_code=404, detail="SyncJob not found")
    if job.status not in ("pending", "running"):
        raise HTTPException(status_code=400, detail=f"Cannot cancel job in status: {job.status}")
    job.status = "failed"
    job.error_message = "Cancelled by user"
    await db.commit()
    return {"status": "cancelled"}
