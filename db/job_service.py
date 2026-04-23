from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from db import settings
from db.compute import get_compute_provider
from db.models import Job, JobStatus

logger = logging.getLogger(__name__)


class JobError(Exception):
    """Domain-level error (maps to 4xx in the API layer)."""


async def _set_job_status(
    db: AsyncSession,
    job: Job,
    status: JobStatus,
    *,
    result: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> Job:
    job.status = status
    job.result = result if status == JobStatus.done else None
    job.error_message = error_message if status == JobStatus.failed else None
    await db.flush()
    return job


async def _dispatch_job(job_id: str, params: dict[str, Any]) -> None:
    provider = get_compute_provider()
    await provider.dispatch(job_id, params)


def _log_task_failure(task: asyncio.Task[None], job_id: str) -> None:
    try:
        exc = task.exception()
    except asyncio.CancelledError:
        logger.warning("Compute dispatch task cancelled for job %s", job_id)
        return
    if exc:
        logger.exception("Compute dispatch failed for job %s", job_id, exc_info=exc)


async def create_job(
    db: AsyncSession,
    params: dict[str, Any],
    owner: str | None = None,
) -> Job:
    job = Job(
        id=str(ULID()),
        status=JobStatus.queued,
        payment_address=settings.payment_wallet_address,
        payment_amount=settings.backtest_price,
        payment_token=settings.payment_token_symbol,
        request_params=params,
        owner=owner,
    )
    db.add(job)
    await db.flush()
    logger.info("Created job %s for owner=%s", job.id, owner)

    task = asyncio.create_task(_dispatch_job(job.id, job.request_params))
    task.add_done_callback(lambda t: _log_task_failure(t, job.id))
    await _set_job_status(db, job, JobStatus.running)
    return job


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
    job = await get_job(db, job_id)
    if job is None:
        raise JobError(f"Job {job_id} not found")
    await _set_job_status(db, job, JobStatus.done, result=result)
    logger.info("Job %s completed successfully", job_id)
    return job


async def fail_job(
    db: AsyncSession,
    job_id: str,
    error_message: str,
) -> Job:
    job = await get_job(db, job_id)
    if job is None:
        raise JobError(f"Job {job_id} not found")
    await _set_job_status(db, job, JobStatus.failed, error_message=error_message)
    logger.warning("Job %s failed: %s", job_id, error_message)
    return job
