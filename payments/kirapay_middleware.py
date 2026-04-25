from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp


class KirapayMiddlewareASGI(BaseHTTPMiddleware):
    """Minimal kirapay gateway middleware for /backtest.

    This middleware is intentionally small and acts as a pluggable seam:
    - routes non-kirapay requests through unchanged
    - validates kirapay request shape/headers
    - marks request state for downstream business logic
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        is_backtest_post = request.method == "POST" and request.url.path == "/backtest"
        if not is_backtest_post:
            return await call_next(request)

        payment_method = (request.headers.get("x-payment-method") or "").strip().lower()
        if payment_method != "kirapay":
            return await call_next(request)

        # Placeholder kirapay verification contract.
        # Replace with real verify call once kirapay API is available.
        kirapay_proof = (request.headers.get("x-kirapay-proof") or "").strip()
        if not kirapay_proof:
            return JSONResponse(
                status_code=402,
                content={"error": "KiraPay proof is required", "code": "kirapay_proof_missing"},
            )

        # Mark request as payment-verified for downstream handlers.
        request.state.kirapay_verified = True
        request.state.payment_method = "kirapay"
        return await call_next(request)
