"""
Application entrypoint.

    uvicorn application.main:application --reload
"""

import logging
from datetime import datetime
from typing import Any

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from db import job_service, settings, webhooks
from db.database import get_db
from payments import PaymentAdapter, X402PaymentAdapter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)-30s %(levelname)-8s %(message)s",
)

class BacktestService:
   

    def __init__(self, payment_adapter: PaymentAdapter | None = None) -> None:
        self.app = FastAPI(
            title="Backtest API",
            summary="Payment gate for paid algorithmic-strategy backtests",
            version="0.1.0",
            docs_url="/docs",
        )
        self.payment_adapter = payment_adapter or X402PaymentAdapter()
        self._setup_middlewares()
        self._setup_routes()

    def _setup_middlewares(self) -> None:
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        self.app.include_router(webhooks.router)

        if settings.app_mode != "test":
            for middleware in self.payment_adapter.get_middleware_specs():
                self.app.add_middleware(middleware.middleware_cls, **middleware.kwargs)

    def _setup_routes(self) -> None:
        class BacktestCreateRequest(BaseModel):
            params: dict[str, Any] = Field(
                ...,
                description="Arbitrary strategy / backtest parameters (forwarded to engine)",
                examples=[
                    {
                        "strategy": "GrindURUS",
                        "symbol": "ETH-USD",
                        "start_date": "2025-01-01",
                        "end_date": "2025-12-31",
                        "timeframe": "1h",
                        "initial_capital": 10000,
                    }
                ],
            )
            owner_address: str | None = Field(
                None,
                description="Wallet address of the requester (for lookup later)",
            )

        class CreateBacktestRequest(BaseModel):
            start_time: datetime
            end_time: datetime
            symbol: str = Field(..., min_length=1)
            base_asset: float = Field(..., gt=0)
            quote_asset: float = Field(..., gt=0)

            @model_validator(mode="after")
            def validate_time_range(self) -> "BacktestService.CreateBacktestRequest":
                if self.end_time <= self.start_time:
                    raise ValueError("end_time must be greater than start_time")
                return self

        class BacktestCreateResponse(BaseModel):
            job_id: str
            status: str
            message: str = "Send payment to proceed. Poll GET /jobs/{job_id} for status."

        class JobStatusResponse(BaseModel):
            job_id: str
            status: str
            created_at: datetime
            updated_at: datetime
            result: dict[str, Any] | None = None
            error_message: str | None = None
            payment_tx_hash: str | None = None
        @self.app.post(
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

        @self.app.post(
            "/create",
            response_model=BacktestCreateResponse,
            status_code=201,
            summary="Create backtest with required strategy fields",
        )
        async def create(
            body: CreateBacktestRequest,
            db: AsyncSession = Depends(get_db),
        ) -> BacktestCreateResponse:
            params = {
                "start_time": body.start_time.isoformat(),
                "end_time": body.end_time.isoformat(),
                "symbol": body.symbol,
                "base_asset": body.base_asset,
                "quote_asset": body.quote_asset,
            }
            job = await job_service.create_job(db, params=params)
            return BacktestCreateResponse(job_id=job.id, status=job.status.value)

        @self.app.get(
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

        @self.app.get("/health", tags=["infra"])
        async def health() -> dict:
            return {"status": "ok"}


service = BacktestService()
app = service.app


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
