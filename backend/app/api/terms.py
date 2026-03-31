# backend/app/api/terms.py
from datetime import datetime, timezone
from typing import Literal, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.term import Term

router = APIRouter()

VALID_STATUSES = {"auto", "confirmed", "rejected"}


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class TermCreate(BaseModel):
    word: str
    variants: Optional[list[str]] = None
    meanings: Optional[list[dict]] = None
    examples: Optional[list[str]] = None
    group_id: Optional[int] = None


class TermPatch(BaseModel):
    word: Optional[str] = None
    variants: Optional[list[str]] = None
    meanings: Optional[list[dict]] = None
    examples: Optional[list[str]] = None
    status: Optional[str] = None
    needs_review: Optional[bool] = None


def _term_to_dict(t: Term) -> dict:
    return {
        "id": str(t.id),
        "word": t.word,
        "variants": t.variants,
        "meanings": t.meanings,
        "examples": t.examples,
        "status": t.status,
        "needs_review": t.needs_review,
        "group_id": t.group_id,
        "created_at": t.created_at,
        "updated_at": t.updated_at,
    }


# ---------------------------------------------------------------------------
# GET /terms
# ---------------------------------------------------------------------------

@router.get("")
async def list_terms(
    status: Literal["auto", "confirmed", "rejected", "all"] = "all",
    needs_review: Optional[bool] = None,
    group_id: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Term)
    if status != "all":
        stmt = stmt.where(Term.status == status)
    if needs_review is not None:
        stmt = stmt.where(Term.needs_review == needs_review)
    if group_id is not None:
        stmt = stmt.where(Term.group_id == group_id)
    stmt = stmt.order_by(Term.needs_review.desc(), Term.updated_at.desc())
    stmt = stmt.offset(offset).limit(limit)

    result = await db.execute(stmt)
    terms = result.scalars().all()
    return [_term_to_dict(t) for t in terms]


# ---------------------------------------------------------------------------
# POST /terms
# ---------------------------------------------------------------------------

@router.post("", status_code=201)
async def create_term(
    body: TermCreate,
    db: AsyncSession = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    term = Term(
        id=uuid4(),
        word=body.word,
        variants=body.variants,
        meanings=body.meanings if body.meanings is not None else [],
        examples=body.examples,
        group_id=body.group_id,
        status="confirmed",
        needs_review=False,
        created_at=now,
        updated_at=now,
    )
    db.add(term)
    await db.flush()
    await db.commit()
    await db.refresh(term)
    return _term_to_dict(term)


# ---------------------------------------------------------------------------
# PATCH /terms/{term_id}
# ---------------------------------------------------------------------------

@router.patch("/{term_id}")
async def patch_term(
    term_id: UUID,
    body: TermPatch,
    db: AsyncSession = Depends(get_db),
):
    term = await db.get(Term, term_id)
    if term is None:
        raise HTTPException(status_code=404, detail="Term not found")

    for field in body.model_fields_set:
        if field == "status":
            value = getattr(body, field)
            if value not in VALID_STATUSES:
                raise HTTPException(
                    status_code=422,
                    detail=f"Invalid status '{value}'. Must be one of: {sorted(VALID_STATUSES)}",
                )
        setattr(term, field, getattr(body, field))

    term.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(term)
    return _term_to_dict(term)
