from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Shared base for all models."""


class JobStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status", native_enum=False),
        default=JobStatus.queued,
        index=True,
    )
    payment_address: Mapped[str] = mapped_column(String(64))
    payment_amount: Mapped[str] = mapped_column(String(32))
    payment_token: Mapped[str] = mapped_column(String(16))
    payment_tx_hash: Mapped[str | None] = mapped_column(String(128), default=None)
    request_params: Mapped[dict] = mapped_column(JSONB, default=dict)
    result: Mapped[dict | None] = mapped_column(JSONB, default=None)
    error_message: Mapped[str | None] = mapped_column(Text, default=None)
    owner: Mapped[str | None] = mapped_column(String(128), default=None, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (Index("ix_jobs_owner_created", "owner", "created_at"),)

    def __repr__(self) -> str:
        return f"<Job {self.id} [{self.status.value}]>"
