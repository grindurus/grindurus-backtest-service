from decimal import Decimal
from enum import Enum
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import BacktestQueue, BacktestsHistory, PromoCode, QueueStatus
from .schemas import HistoryCreate, QueueCreate


async def enqueue_backtest(db: AsyncSession, payload: QueueCreate) -> BacktestQueue:
    item = BacktestQueue(**payload.model_dump(), status=QueueStatus.pending)
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


async def pop_next_backtest(db: AsyncSession) -> BacktestQueue | None:
    query = (
        select(BacktestQueue)
        .where(BacktestQueue.status == QueueStatus.pending)
        .order_by(BacktestQueue.priority_usdc.desc(), BacktestQueue.created_at.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    result = await db.execute(query)
    item = result.scalar_one_or_none()
    if item is None:
        return None

    item.status = QueueStatus.processing
    await db.commit()
    await db.refresh(item)
    return item


async def update_queue_status(db: AsyncSession, queue_id: str, status: QueueStatus) -> BacktestQueue | None:
    item = await db.get(BacktestQueue, queue_id)
    if item is None:
        return None
    item.status = status
    await db.commit()
    await db.refresh(item)
    return item


async def increase_queue_priority(db: AsyncSession, queue_id: str, delta_usdc: Decimal) -> BacktestQueue | None:
    item = await db.get(BacktestQueue, queue_id)
    if item is None:
        return None
    item.priority_usdc = (item.priority_usdc or Decimal("0")) + delta_usdc
    await db.commit()
    await db.refresh(item)
    return item


async def list_queue(
    db: AsyncSession,
    limit: int = 100,
    status: QueueStatus | None = None,
    sort_by: Literal["priority", "created_at"] = "priority",
    sort_order: Literal["asc", "desc"] = "asc",
) -> list[BacktestQueue]:
    query = select(BacktestQueue)
    if status is not None:
        query = query.where(BacktestQueue.status == status)
    if sort_by == "created_at":
        primary = BacktestQueue.created_at
        secondary = BacktestQueue.priority_usdc
    else:
        primary = BacktestQueue.priority_usdc
        secondary = BacktestQueue.created_at

    if sort_order == "desc":
        query = query.order_by(primary.desc(), secondary.desc())
    else:
        query = query.order_by(primary.asc(), secondary.asc())

    query = query.limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


async def add_history_record(db: AsyncSession, payload: HistoryCreate) -> BacktestsHistory:
    item = BacktestsHistory(**payload.model_dump())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


async def list_history(db: AsyncSession, limit: int = 100) -> list[BacktestsHistory]:
    query = select(BacktestsHistory).order_by(BacktestsHistory.created_at.desc()).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


class PromoCodeConsumeResult(str, Enum):
    accepted = "accepted"
    invalid = "invalid"
    exhausted = "exhausted"


async def consume_promocode(db: AsyncSession, code: str) -> tuple[PromoCodeConsumeResult, int | None]:
    normalized = code.strip().upper()
    item = await db.get(PromoCode, normalized, with_for_update=True)
    if item is None or not item.is_active:
        await db.rollback()
        return PromoCodeConsumeResult.invalid, None
    if item.remaining_uses <= 0:
        await db.rollback()
        return PromoCodeConsumeResult.exhausted, 0

    item.remaining_uses -= 1
    await db.commit()
    await db.refresh(item)
    return PromoCodeConsumeResult.accepted, item.remaining_uses


async def get_promocode(db: AsyncSession, code: str) -> PromoCode | None:
    normalized = code.strip().upper()
    return await db.get(PromoCode, normalized)


async def add_promocode_uses(db: AsyncSession, code: str, amount: int) -> PromoCode:
    normalized = code.strip().upper()
    item = await db.get(PromoCode, normalized, with_for_update=True)
    if item is None:
        item = PromoCode(code=normalized, remaining_uses=amount, is_active=True)
        db.add(item)
    else:
        item.remaining_uses += amount
        item.is_active = True
    await db.commit()
    await db.refresh(item)
    return item


async def list_promocodes(db: AsyncSession, limit: int = 100) -> list[PromoCode]:
    query = select(PromoCode).order_by(PromoCode.created_at.desc()).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


async def set_promocode_uses(db: AsyncSession, code: str, remaining_uses: int, is_active: bool = True) -> PromoCode:
    normalized = code.strip().upper()
    item = await db.get(PromoCode, normalized, with_for_update=True)
    if item is None:
        item = PromoCode(code=normalized, remaining_uses=remaining_uses, is_active=is_active)
        db.add(item)
    else:
        item.remaining_uses = remaining_uses
        item.is_active = is_active
    await db.commit()
    await db.refresh(item)
    return item
