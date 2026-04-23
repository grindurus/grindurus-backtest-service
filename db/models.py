import enum
import uuid
from datetime import datetime
from decimal import Decimal
from random import choices
from string import ascii_uppercase, digits

from sqlalchemy import DateTime, Enum, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class QueueStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    done = "done"
    failed = "failed"


def generate_queue_id() -> str:
    alphabet = digits + ascii_uppercase
    return "".join(choices(alphabet, k=26))


class BacktestsHistory(Base):
    __tablename__ = "backtests_history"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    base_asset: Mapped[str] = mapped_column(String(32), nullable=False)
    quote_asset: Mapped[str] = mapped_column(String(32), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    base_balance_start: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    base_balance_end: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    quote_balance_start: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    quote_balance_end: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    pnl_base: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    pnl_quote: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    creator_address: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BacktestQueue(Base):
    __tablename__ = "backtest_queue"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=generate_queue_id)
    base_asset: Mapped[str] = mapped_column(String(32), nullable=False)
    quote_asset: Mapped[str] = mapped_column(String(32), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    base_balance_start: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    quote_balance_start: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    priority_usdc: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    creator_address: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[QueueStatus] = mapped_column(
        Enum(QueueStatus, name="queue_status"),
        nullable=False,
        default=QueueStatus.pending,
        server_default=QueueStatus.pending.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
