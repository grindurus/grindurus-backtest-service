

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from application import settings
from application.models import Job, JobStatus

from application.compute import LocalProvider


compute_provider = LocalProvider()

logger = logging.getLogger(__name__)

class JobError(Exception):
    """Domain-level error (maps to 4xx in the API layer)."""
    pass


# ── Create ────────────────────────────────────────────────────
async def create_job(
    db: AsyncSession,
    params: dict[str, Any],
    owner: str | None = None,
) -> Job:
    """Create a new backtest job in awaiting_payment state."""
    job = Job(
        id=str(ULID()),
        status=JobStatus.queued, # x402 takes care about all of this
        payment_address=settings.payment_wallet_address,
        payment_amount=settings.backtest_price,
        payment_token=settings.payment_token_symbol,
        request_params=params,
        owner=owner,
    )
    db.add(job)
    await db.flush()
    logger.info("Created job %s for owner=%s", job.id, owner)

    task = asyncio.create_task(compute_provider.dispatch(job.id, job.request_params))
    task.add_done_callback(lambda t: logger.error(f"Task failed: {t.exception()}") if t.exception() else None)

    job.status = JobStatus.running
    await db.flush()

    return job


# ── Read ──────────────────────────────────────────────────────
async def get_job(db: AsyncSession, job_id: str) -> Job | None:
    return await db.get(Job, job_id)


async def list_jobs_for_owner(
    db: AsyncSession,
    owner: str,
    limit: int = 50,
    offset: int = 0,
) -> list[Job]:
    stmt = (
        select(Job)
        .where(Job.owner == owner)
        .order_by(Job.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def complete_job(
    db: AsyncSession,
    job_id: str,
    result: dict[str, Any],
) -> Job:
    """Called by the compute worker on success."""
    job = await get_job(db, job_id)
    if job is None:
        raise JobError(f"Job {job_id} not found")
    job.result = result
    job.status = JobStatus.done
    await db.flush()
    logger.info("Job %s completed successfully", job_id)
    return job


async def fail_job(
    db: AsyncSession,
    job_id: str,
    error_message: str,
) -> Job:
    """Called by the compute worker on failure."""
    job = await get_job(db, job_id)
    if job is None:
        raise JobError(f"Job {job_id} not found")
    job.error_message = error_message
    await db.flush()
    logger.warning("Job %s failed: %s", job_id, error_message)
    return job

