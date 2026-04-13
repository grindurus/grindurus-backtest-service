"""
Application entrypoint.

    uvicorn application.main:application --reload
"""

import logging

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from x402 import x402ResourceServer
from x402.http.middleware.fastapi import PaymentMiddlewareASGI
from x402.mechanisms.evm.exact import ExactEvmServerScheme
from x402.http import PaymentOption, HTTPFacilitatorClient, FacilitatorConfig
from x402.http.types import RouteConfig

from application import job_service, settings, webhooks
from application.database import get_db
from application.schemas import BacktestCreateRequest, BacktestCreateResponse, JobStatusResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)-30s %(levelname)-8s %(message)s",
)

app = FastAPI(
    title="Backtest API",
    summary="Payment gate for paid algorithmic-strategy backtests",
    version="0.1.0",
    docs_url="/docs",
)

# CORS — lock this down in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(webhooks.router)

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
                price=settings.backtest_price,
                network=settings.payment_wallet_network,
            ),
        ],
        mime_type="application/json",
        description="Order a backtest",
    ),
}

if settings.app_mode != "test":
    app.add_middleware(PaymentMiddlewareASGI, routes=routes, server=server)



@app.post(
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

@app.get(
    "/jobs/{job_id}",
    response_model=JobStatusResponse,
    summary="Check job status",
    description=(
        "Poll this endpoint after payment to track progress. "
        "When status is 'done', the result field contains backtest output."
    ),
)

@app.get("/health", tags=["infra"])
async def health() -> dict:
    return {"status": "ok"}



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

