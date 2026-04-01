from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SyncJob(Base):
    __tablename__ = "sync_jobs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    group_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("groups.id"))
    from_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    to_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String, default="pending")
    checkpoint_message_id: Mapped[int | None] = mapped_column(BigInteger)
    checkpoint_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    group: Mapped["Group"] = relationship(back_populates="sync_jobs")


class QaSession(Base):
    __tablename__ = "qa_sessions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str | None] = mapped_column(Text)
    group_id: Mapped[int | None] = mapped_column(BigInteger)
    llm_model: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    context: Mapped[list["QaContext"]] = relationship(back_populates="session")


class QaContext(Base):
    __tablename__ = "qa_context"

    qa_session_id: Mapped[UUID] = mapped_column(
        ForeignKey("qa_sessions.id"), primary_key=True
    )
    slice_id: Mapped[UUID] = mapped_column(ForeignKey("slices.id"), primary_key=True)
    similarity: Mapped[float | None] = mapped_column(Float)
    rank: Mapped[int | None] = mapped_column(Integer)

    session: Mapped["QaSession"] = relationship(back_populates="context")
