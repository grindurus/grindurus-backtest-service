from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

from db.database import SessionLocal
from db.queries import PromoCodeConsumeResult, consume_promocode


class PromocodeMiddlewareASGI(BaseHTTPMiddleware):
    """Validate and consume promocode for POST /backtest."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        is_backtest_post = request.method == "POST"
        if not is_backtest_post:
            return await call_next(request)

        payment_method = (request.headers.get("x-payment-method") or "").strip().lower()
        if payment_method != "promocode":
            return await call_next(request)

        code = (request.headers.get("x-promocode") or "").strip().upper()
        if not code:
            return JSONResponse(
                status_code=402,
                content={"error": "Promocode is required", "code": "promocode_missing"},
            )

        async with SessionLocal() as db:
            result, remaining = await consume_promocode(db, code)

        if result == PromoCodeConsumeResult.invalid:
            return JSONResponse(
                status_code=405,
                content={"error": "Invalid promocode", "code": "promocode_invalid"},
            )
        if result == PromoCodeConsumeResult.exhausted:
            return JSONResponse(
                status_code=406,
                content={"error": "Promocode exhausted", "code": "promocode_exhausted"},
            )

        request.state.promocode_verified = True
        request.state.promocode_code = code
        request.state.promocode_remaining_uses = remaining
        request.state.payment_method = "promocode"
        return await call_next(request)
