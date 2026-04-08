"""
Job service — all business logic for the job lifecycle lives here.

API routes stay thin; this module owns validation, state transitions,
and side-effects (dispatching to compute, etc.).
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from app.core.config import settings
from app.models.job import Job, JobStatus
from app.services.compute import get_compute_provider

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
        status=JobStatus.awaiting_payment,
        payment_address=settings.payment_wallet_address,
        payment_amount=settings.backtest_price_amount,
        payment_token=settings.payment_token_symbol,
        request_params=params,
        owner=owner,
    )
    db.add(job)
    await db.flush()  # assign server defaults (created_at etc.)
    logger.info("Created job %s for owner=%s", job.id, owner)
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


# ── State transitions ─────────────────────────────────────────
def _transition(job: Job, target: JobStatus) -> None:
    """Validate and apply a state transition."""
    if not job.can_transition_to(target):
        raise JobError(
            f"Cannot transition job {job.id} from {job.status.value} to {target.value}"
        )
    old = job.status
    job.status = target
    logger.info("Job %s: %s → %s", job.id, old.value, target.value)


async def confirm_payment(
    db: AsyncSession,
    job_id: str,
    tx_hash: str,
) -> Job:
    """
    Mark payment as confirmed and advance to 'queued'.
    Then dispatch to the compute provider.
    """
    job = await get_job(db, job_id)
    if job is None:
        raise JobError(f"Job {job_id} not found")

    # Step 1: payment_confirmed
    _transition(job, JobStatus.payment_confirmed)
    job.payment_tx_hash = tx_hash

    # Step 2: immediately queue
    _transition(job, JobStatus.queued)
    await db.flush()

    # Step 3: dispatch to compute (fire-and-forget)
    provider = get_compute_provider()
    await provider.dispatch(job.id, job.request_params)

    return job


async def mark_running(db: AsyncSession, job_id: str) -> Job:
    """Called by the compute worker when it starts the backtest."""
    job = await get_job(db, job_id)
    if job is None:
        raise JobError(f"Job {job_id} not found")
    _transition(job, JobStatus.running)
    await db.flush()
    return job


async def complete_job(
    db: AsyncSession,
    job_id: str,
    result: dict[str, Any],
) -> Job:
    """Called by the compute worker on success."""
    job = await get_job(db, job_id)
    if job is None:
        raise JobError(f"Job {job_id} not found")
    _transition(job, JobStatus.done)
    job.result = result
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
    _transition(job, JobStatus.failed)
    job.error_message = error_message
    await db.flush()
    logger.warning("Job %s failed: %s", job_id, error_message)
    return job