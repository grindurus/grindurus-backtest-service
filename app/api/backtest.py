"""
/backtest and /jobs endpoints — the public-facing API.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.backtest import (
    BacktestCreateRequest,
    BacktestCreateResponse,
    JobStatusResponse,
)
from app.services import job_service

router = APIRouter(tags=["backtest"])


@router.post(
    "/backtest",
    response_model=BacktestCreateResponse,
    status_code=201,
    summary="Order a backtest",
    description=(
        "Creates a backtest job and returns payment instructions. "
        "The frontend should prompt the user to send payment, then "
        "poll GET /jobs/{job_id} until status is 'done'."
    ),
)
async def create_backtest(
    body: BacktestCreateRequest,
    db: AsyncSession = Depends(get_db),
) -> BacktestCreateResponse:
    job = await job_service.create_job(
        db,
        params=body.params,
        owner=body.owner_address,
    )
    return BacktestCreateResponse(
        job_id=job.id,
        status=job.status.value,
        payment_address=job.payment_address,
        payment_amount=job.payment_amount,
        payment_token=job.payment_token,
    )


@router.get(
    "/jobs/{job_id}",
    response_model=JobStatusResponse,
    summary="Check job status",
    description=(
        "Poll this endpoint after payment to track progress. "
        "When status is 'done', the result field contains backtest output."
    ),
)
async def get_job_status(
    job_id: str,
    db: AsyncSession = Depends(get_db),
) -> JobStatusResponse:
    job = await job_service.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    return JobStatusResponse(
        job_id=job.id,
        status=job.status.value,
        created_at=job.created_at,
        updated_at=job.updated_at,
        result=job.result if job.status.value == "done" else None,
        error_message=job.error_message if job.status.value == "failed" else None,
        payment_tx_hash=job.payment_tx_hash,
    )