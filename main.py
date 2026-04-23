import logging
from datetime import datetime
from decimal import Decimal

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_db, init_db
from db.models import QueueStatus
from db.schemas import (
    HistoryCreate,
    HistoryItemResponse,
    QueueCreate,
    QueueItemResponse,
    QueueStatusUpdate,
)
from db.service import (
    add_history_record,
    enqueue_backtest,
    list_queue,
    list_history,
    pop_next_backtest,
    update_queue_status,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)-30s %(levelname)-8s %(message)s",
)


class BacktestService:
    def __init__(self) -> None:
        self.app = FastAPI(
            title="Backtest API",
            summary="Backtests queue and history service",
            version="0.1.0",
            docs_url="/docs",
        )
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

        @self.app.on_event("startup")
        async def _startup_init_db() -> None:
            await init_db()
            logging.info("Database schema ensured")

    def _setup_routes(self) -> None:
        class BacktestRequest(BaseModel):
            # New flat format.
            base_asset: str | None = None
            quote_asset: str | None = None
            period_start: datetime | None = None
            period_end: datetime | None = None
            base_balance_start: Decimal | None = None
            quote_balance_start: Decimal | None = None
            priority_usdc: Decimal | None = None
            creator_address: str | None = None
            payment_method: str | None = None

            # Legacy format.
            params: dict | None = None
            owner_address: str | None = None

            @model_validator(mode="after")
            def normalize_and_validate(self) -> "BacktestRequest":
                if self.params is not None:
                    params = self.params
                    self.base_asset = self.base_asset or params.get("base_asset")
                    self.quote_asset = self.quote_asset or params.get("quote_asset")
                    self.period_start = self.period_start or params.get("period_start") or params.get("date_from")
                    self.period_end = self.period_end or params.get("period_end") or params.get("date_to")
                    self.base_balance_start = (
                        self.base_balance_start
                        or params.get("base_balance_start")
                        or params.get("base_amount")
                    )
                    self.quote_balance_start = (
                        self.quote_balance_start
                        or params.get("quote_balance_start")
                        or params.get("quote_amount")
                    )
                    self.priority_usdc = self.priority_usdc or params.get("priority_usdc") or Decimal("0")
                    self.creator_address = self.creator_address or self.owner_address or params.get("creator_address")
                    self.payment_method = self.payment_method or params.get("payment_method") or params.get("pay_method")

                missing_fields = [
                    field
                    for field in (
                        "base_asset",
                        "quote_asset",
                        "period_start",
                        "period_end",
                        "base_balance_start",
                        "quote_balance_start",
                        "priority_usdc",
                        "creator_address",
                    )
                    if getattr(self, field) is None
                ]
                if missing_fields:
                    raise ValueError(f"Missing required fields: {', '.join(missing_fields)}")
                return self

        @self.app.post(
            "/backtest",
            response_model=QueueItemResponse,
            status_code=201,
            summary="Put backtest into queue",
        )
        async def add_backtest(
            body: BacktestRequest,
            db: AsyncSession = Depends(get_db),
        ) -> QueueItemResponse:
            queue_payload = QueueCreate(
                base_asset=body.base_asset,
                quote_asset=body.quote_asset,
                period_start=body.period_start,
                period_end=body.period_end,
                base_balance_start=body.base_balance_start,
                quote_balance_start=body.quote_balance_start,
                priority_usdc=body.priority_usdc,
                creator_address=body.creator_address,
            )
            return await enqueue_backtest(db, queue_payload)

        @self.app.get(
            "/queue",
            response_model=list[QueueItemResponse],
            summary="List queue sorted by priority and FIFO",
        )
        async def get_queue(
            limit: int = 100,
            status: QueueStatus | None = None,
            db: AsyncSession = Depends(get_db),
        ) -> list[QueueItemResponse]:
            if limit < 1 or limit > 1000:
                raise HTTPException(status_code=400, detail="limit should be in range [1, 1000]")
            return await list_queue(db, limit=limit, status=status)

        @self.app.post(
            "/queue/next",
            response_model=QueueItemResponse,
            summary="Get next backtest by priority and FIFO",
        )
        async def get_next_queue_item(db: AsyncSession = Depends(get_db)) -> QueueItemResponse:
            item = await pop_next_backtest(db)
            if item is None:
                raise HTTPException(status_code=404, detail="No pending backtests in queue")
            return item

        @self.app.patch(
            "/queue/{queue_id}/status",
            response_model=QueueItemResponse,
            summary="Update queue item status",
        )
        async def patch_queue_status(
            queue_id: str,
            body: QueueStatusUpdate,
            db: AsyncSession = Depends(get_db),
        ) -> QueueItemResponse:
            item = await update_queue_status(db, queue_id, body.status)
            if item is None:
                raise HTTPException(status_code=404, detail="Queue item not found")
            return item

        @self.app.post(
            "/history",
            response_model=HistoryItemResponse,
            status_code=201,
            summary="Add completed backtest history record",
        )
        async def create_history_item(
            body: HistoryCreate,
            db: AsyncSession = Depends(get_db),
        ) -> HistoryItemResponse:
            return await add_history_record(db, body)

        @self.app.get(
            "/history",
            response_model=list[HistoryItemResponse],
            summary="List backtest history",
        )
        async def get_history(limit: int = 100, db: AsyncSession = Depends(get_db)) -> list[HistoryItemResponse]:
            if limit < 1 or limit > 1000:
                raise HTTPException(status_code=400, detail="limit should be in range [1, 1000]")
            return await list_history(db, limit=limit)

        @self.app.get("/health", tags=["infra"])
        async def health() -> dict:
            return {"status": "ok"}


service = BacktestService()
app = service.app


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)
