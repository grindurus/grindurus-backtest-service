"""
/backtest and /jobs endpoints — the public-facing API.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from x402 import  x402ResourceServer
from x402.mechanisms.evm.exact import ExactEvmServerScheme

from app.core.config import settings
from app.core.database import get_db
from app.schemas.backtest import (
    BacktestCreateRequest,
    BacktestCreateResponse,
    JobStatusResponse,
)
from app.services import job_service

router = APIRouter(tags=["backtest"])

from x402.http import PaymentOption, HTTPFacilitatorClient, FacilitatorConfig
from x402.http.types import RouteConfig

facilitator = HTTPFacilitatorClient(
    FacilitatorConfig(url="https://x402.org/facilitator")
)
server = x402ResourceServer(facilitator)
server.register(settings.payment_wallet_network, ExactEvmServerScheme())


routes: dict[str, RouteConfig] = {
    "POST /backtest": RouteConfig(
        accepts=[
            PaymentOption(
                scheme="exact",
                pay_to=settings.payment_wallet_address,
                price=settings.backtest_price_amount,
                network=settings.payment_wallet_network,
            ),
        ],
        mime_type="application/json",
        description="Order a backtest",
    ),
}


@router.post(
    "/backtest",
    response_model=BacktestCreateResponse,
    status_code=201,
    summary="Order a backtest",
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