from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import BacktestQueue, BacktestsHistory, QueueStatus
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


async def list_queue(
    db: AsyncSession,
    limit: int = 100,
    status: QueueStatus | None = None,
) -> list[BacktestQueue]:
    query = select(BacktestQueue)
    if status is not None:
        query = query.where(BacktestQueue.status == status)
    query = query.order_by(BacktestQueue.priority_usdc.desc(), BacktestQueue.created_at.asc()).limit(limit)
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
