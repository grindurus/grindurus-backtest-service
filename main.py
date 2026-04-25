# $ python3 main.py

import logging
import json
import asyncio
from contextlib import suppress
from collections.abc import Awaitable, Callable
from typing import Any, Literal
from datetime import datetime
from decimal import Decimal

from fastapi import FastAPI, Depends, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, model_validator
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import JSONResponse

from x402.http import (
    AuthHeaders,
    AuthProvider,
    FacilitatorConfig,
    HTTPFacilitatorClient,
    PaymentOption,
)
from x402.http.middleware.fastapi import PaymentMiddlewareASGI
from x402.http.types import RouteConfig
from x402.mechanisms.evm.exact import ExactEvmServerScheme
from x402.mechanisms.evm.utils import get_network_config
from x402.mechanisms.svm.exact import ExactSvmServerScheme
from x402.server import x402ResourceServer

from payments import KirapayMiddlewareASGI, PromocodeMiddlewareASGI
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
from db.settings import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)-30s %(levelname)-8s %(message)s",
)


class X402Middleware:
    class SafePaymentMiddlewareASGI(PaymentMiddlewareASGI):
        @staticmethod
        def _build_verify_error_response(message: str) -> JSONResponse | None:
            if "Facilitator verify failed" not in message:
                return None

            details: dict = {}
            if ": " in message:
                maybe_json = message.split(": ", 1)[1]
                try:
                    parsed = json.loads(maybe_json)
                    if isinstance(parsed, dict):
                        details = parsed
                except json.JSONDecodeError:
                    details = {}

            return JSONResponse(
                status_code=400,
                content={
                    "error": details.get("invalidReason", message),
                    "details": details or {"raw": message},
                },
            )

        async def dispatch(
            self,
            request: Request,
            call_next: Callable[[Request], Awaitable[Response]],
        ) -> Response:
            if request.method == "POST":
                method = (
                    getattr(request.state, "payment_method", None)
                    or request.headers.get("x-payment-method")
                    or "x402"
                )
                if str(method).strip().lower() != "x402":
                    return await call_next(request)
            try:
                return await super().dispatch(request, call_next)
            except Exception as exc:
                stack = [exc]
                while stack:
                    cur = stack.pop()
                    response = self._build_verify_error_response(str(cur))
                    if response is not None:
                        return response

                    nested = getattr(cur, "exceptions", None)
                    if nested:
                        stack.extend(nested)
                    cause = getattr(cur, "__cause__", None)
                    if cause is not None:
                        stack.append(cause)
                    context = getattr(cur, "__context__", None)
                    if context is not None:
                        stack.append(context)
                raise

    @staticmethod
    def _normalize_price(value: str) -> str:
        return s if (s := value.strip()).startswith("$") else f"${s}"

    @staticmethod
    def _evm_supports_usdc_default(network: str) -> bool:
        try:
            config = get_network_config(network)
        except ValueError:
            return False
        asset = config.get("default_asset")
        return bool(asset and asset.get("address"))

    @staticmethod
    def _build_facilitator_config() -> FacilitatorConfig:
        api_key = settings.x402_api_key.strip()
        if not api_key:
            return FacilitatorConfig(url=settings.x402_facilitator_url)

        class _ApiKeyAuthProvider(AuthProvider):
            def get_auth_headers(self) -> AuthHeaders:
                protected = {
                    "Authorization": f"Bearer {api_key}",
                    "X-API-Key": api_key,
                }
                return AuthHeaders(
                    verify=protected,
                    settle=protected,
                    supported={"X-API-Key": api_key},
                )

        return FacilitatorConfig(
            url=settings.x402_facilitator_url,
            auth_provider=_ApiKeyAuthProvider(),
        )

    def setup(self, app: FastAPI) -> None:
        facilitator = HTTPFacilitatorClient(self._build_facilitator_config())
        server = x402ResourceServer(facilitator)
        supported = facilitator.get_supported()

        registered_evm: list[str] = []
        registered_svm: list[str] = []
        for kind in supported.kinds:
            if kind.x402_version != 2 or kind.scheme != "exact":
                continue
            net = kind.network
            if net.startswith("eip155:"):
                server.register(net, ExactEvmServerScheme())
                registered_evm.append(net)
            elif net.startswith("solana:"):
                server.register(net, ExactSvmServerScheme())
                registered_svm.append(net)

        logging.info(
            "x402 v2/exact schemes registered: evm=%s svm=%s",
            registered_evm,
            registered_svm,
        )

        price = self._normalize_price(settings.backtest_price)
        evm_payable = [n for n in registered_evm if self._evm_supports_usdc_default(n)]
        skipped_evm = sorted(set(registered_evm) - set(evm_payable))
        if skipped_evm:
            logging.warning(
                "Skipping EVM networks without default stablecoin for $ price: %s",
                skipped_evm,
            )

        accepts: list[PaymentOption] = [
            PaymentOption(
                scheme="exact",
                pay_to=settings.evm_payment_address,
                price=price,
                network=evm_network,
            )
            for evm_network in evm_payable
        ]
        accepts.extend(
            PaymentOption(
                scheme="exact",
                pay_to=settings.svm_payment_addess,
                price=price,
                network=svm_network,
            )
            for svm_network in registered_svm
        )
        if not accepts:
            fallback_network = settings.x402_network if self._evm_supports_usdc_default(settings.x402_network) else "eip155:8453"
            accepts = [
                PaymentOption(
                    scheme="exact",
                    pay_to=settings.evm_payment_address,
                    price=price,
                    network=fallback_network,
                )
            ]
        logging.info(f'accepts: {accepts}')
        routes: dict[str, RouteConfig] = {
            "POST /backtest": RouteConfig(
                accepts=accepts,
                mime_type="application/json",
                description="Create a backtest job in queue",
            ),
        }

        app.add_middleware(self.SafePaymentMiddlewareASGI, routes=routes, server=server)
        app.state.x402_supported_networks = [*registered_evm, *registered_svm]
        app.state.x402_network = settings.x402_network
        app.state.x402_registered = {"evm": registered_evm, "svm": registered_svm}


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
