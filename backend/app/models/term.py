from __future__ import annotations

from datetime import datetime, timezone
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
    status: Mapped[str] = mapped_column(String, default="auto")
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    group_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("groups.id"))
    llm_model: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )
