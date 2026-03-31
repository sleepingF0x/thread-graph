from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Topic(Base):
    __tablename__ = "topics"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    group_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("groups.id"))
    name: Mapped[str | None] = mapped_column(String(64))
    summary: Mapped[str | None] = mapped_column(Text)
    summary_version: Mapped[int] = mapped_column(Integer, default=0)
    llm_model: Mapped[str | None] = mapped_column(String)
    time_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    time_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    slice_count: Mapped[int] = mapped_column(Integer, default=0)

    slices: Mapped[list["SliceTopic"]] = relationship(back_populates="topic")


class SliceTopic(Base):
    __tablename__ = "slice_topics"

    slice_id: Mapped[UUID] = mapped_column(
        ForeignKey("slices.id"), primary_key=True, unique=True
    )
    topic_id: Mapped[UUID] = mapped_column(ForeignKey("topics.id"), primary_key=True)
    similarity: Mapped[float | None] = mapped_column(Float)

    slice: Mapped["Slice"] = relationship(back_populates="topic_link")
    topic: Mapped["Topic"] = relationship(back_populates="slices")
