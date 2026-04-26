# $ python3 main.py

import logging
import asyncio
from contextlib import suppress
from typing import Any, Literal
from datetime import datetime
from decimal import Decimal

from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, model_validator
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import JSONResponse

from payments.kirapay_middleware import KirapayMiddlewareASGI
from payments.promocode_middleware import PromocodeMiddlewareASGI
from payments.x402_middleware import X402Middleware
from db.database import SessionLocal, get_db, init_db
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
    increase_queue_priority,
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
    SUPPORTED_PAYMENT_METHODS = {"x402", "kirapay", "promocode"}

    def __init__(self) -> None:
        self.app = FastAPI(
            title="Backtest API",
            summary="Backtests queue and history service",
            version="0.1.0",
            docs_url="/docs",
        )
        self._priority_update_queue: asyncio.Queue[tuple[str, Decimal]] = asyncio.Queue()
        self._priority_worker: asyncio.Task | None = None
        self._setup_middlewares()
        self._setup_routes()

    def _setup_middlewares(self) -> None:
        @self.app.middleware("http")
        async def payment_method_dispatcher(request: Request, call_next):
            if request.method == "POST":
                method = (request.headers.get("x-payment-method") or "").strip().lower()
                if not method:
                    return JSONResponse(
                        status_code=400,
                        content={"error": "Missing X-Payment-Method header"},
                    )
                if method not in self.SUPPORTED_PAYMENT_METHODS:
                    return JSONResponse(
                        status_code=501,
                        content={"error": f"Payment method '{method}' is not enabled"},
                    )
                request.state.payment_method = method

            return await call_next(request)

        self.app.add_middleware(KirapayMiddlewareASGI)
        self.app.add_middleware(PromocodeMiddlewareASGI)
        X402Middleware().setup(self.app)
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["http://localhost:3001", "http://127.0.0.1:3001", "https://app.grindurus.xyz"],
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["PAYMENT-REQUIRED", "PAYMENT-RESPONSE", "X-PAYMENT-RESPONSE"],
        )

        @self.app.on_event("startup")
        async def _startup_init_db() -> None:
            await init_db()
            logging.info("Database schema ensured")
            self._priority_worker = asyncio.create_task(self._priority_update_task())

        @self.app.on_event("shutdown")
        async def _shutdown_priority_worker() -> None:
            if self._priority_worker is None:
                return
            self._priority_worker.cancel()
            with suppress(asyncio.CancelledError):
                await self._priority_worker
            self._priority_worker = None

    async def _before_payment_hook(self, context: Any) -> None:
        logging.info(f"x402 before_payment: ctx={context}")

    async def _after_payment_hook(self, context: Any) -> None:
        logging.info(f"x402 after_payment: ctx={context}")

    async def _priority_update_task(self) -> None:
        while True:
            backtest_id, delta = await self._priority_update_queue.get()
            try:
                delta_usdc = Decimal(str(delta))
                async with SessionLocal() as db:
                    updated = await increase_queue_priority(db, backtest_id, delta_usdc)
                if updated is None:
                    logging.warning("priority worker: queue_id=%s not found", backtest_id)
                else:
                    logging.info(
                        "priority worker: queue_id=%s delta=%s new_priority=%s",
                        backtest_id,
                        delta_usdc,
                        updated.priority_usdc,
                    )
            except Exception:
                logging.exception("priority worker: failed for queue_id=%s delta=%s", backtest_id, delta)
            finally:
                self._priority_update_queue.task_done()

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
            wallet_network: str | None = None

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
                    self.wallet_network = self.wallet_network or params.get("wallet_network")

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

        class BidRequest(BaseModel):
            amount_usdc: Decimal

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
                priority_usdc=Decimal("0"),
                creator_address=body.creator_address,
            )
            item = await enqueue_backtest(db, queue_payload)
            logging.info("priority queued: queue_id=%s delta=%s", item.id, body.priority_usdc)
            await self._priority_update_queue.put((item.id, body.priority_usdc))
            return item

        @self.app.post(
            "/backtest/{queue_id}/bid",
            response_model=QueueItemResponse,
            summary="Increase queue priority via paid bid",
        )
        async def bid_backtest(
            queue_id: str,
            body: BidRequest,
            db: AsyncSession = Depends(get_db),
        ) -> QueueItemResponse:
            amount = Decimal(str(body.amount_usdc))
            if amount <= 0:
                raise HTTPException(status_code=400, detail="amount_usdc must be greater than zero")
            updated = await increase_queue_priority(db, queue_id, amount)
            if updated is None:
                raise HTTPException(status_code=404, detail="Queue item not found")
            logging.info("bid accepted: queue_id=%s delta=%s new_priority=%s", queue_id, amount, updated.priority_usdc)
            return updated

        @self.app.get(
            "/queue",
            response_model=list[QueueItemResponse],
            summary="List queue sorted by priority and FIFO",
        )
        async def get_queue(
            limit: int = 100,
            status: QueueStatus | None = None,
            sort_by: Literal["priority", "created_at"] = "priority",
            sort_order: Literal["asc", "desc"] = "asc",
            db: AsyncSession = Depends(get_db),
        ) -> list[QueueItemResponse]:
            if limit < 1 or limit > 1000:
                raise HTTPException(status_code=400, detail="limit should be in range [1, 1000]")
            return await list_queue(
                db,
                limit=limit,
                status=status,
                sort_by=sort_by,
                sort_order=sort_order,
            )

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
