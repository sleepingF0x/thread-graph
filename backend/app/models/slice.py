from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Slice(Base):
    __tablename__ = "slices"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    group_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("groups.id"))
    time_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    time_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="pending")
    pg_done: Mapped[bool] = mapped_column(Boolean, default=False)
    qdrant_done: Mapped[bool] = mapped_column(Boolean, default=False)
    llm_done: Mapped[bool] = mapped_column(Boolean, default=False)
    embedding_model: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )

    messages: Mapped[list["SliceMessage"]] = relationship(back_populates="slice")
    topic_link: Mapped["SliceTopic | None"] = relationship(back_populates="slice")


class SliceMessage(Base):
    __tablename__ = "slice_messages"

    slice_id: Mapped[UUID] = mapped_column(ForeignKey("slices.id"), primary_key=True)
    message_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    group_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    position: Mapped[int] = mapped_column(Integer)

    slice: Mapped["Slice"] = relationship(back_populates="messages")
