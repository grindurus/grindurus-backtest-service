from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

from db.settings import settings


class PromocodeMiddlewareASGI(BaseHTTPMiddleware):
    """Validate promocode payment method for POST /backtest."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    @staticmethod
    def _allowed_codes() -> set[str]:
        raw = settings.promocode_payment_codes.strip()
        if not raw:
            return set()
        return {code.strip().upper() for code in raw.split(",") if code.strip()}

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

        allowed = self._allowed_codes()
        if code not in allowed:
            return JSONResponse(
                status_code=402,
                content={"error": "Invalid promocode", "code": "promocode_invalid"},
            )

        request.state.promocode_verified = True
        request.state.payment_method = "promocode"
        return await call_next(request)
