"""x402 middleware integration for backtest service."""

from __future__ import annotations

import asyncio
import base64
import binascii
import dataclasses
import json
import logging
import threading
import time
import uuid
from collections.abc import Awaitable, Callable
from decimal import Decimal, InvalidOperation
from typing import Any

from cryptography.hazmat.primitives.serialization import load_der_private_key
from fastapi import FastAPI, Request, Response
from starlette.responses import JSONResponse
from x402.http import (
    AuthHeaders,
    AuthProvider,
    FacilitatorConfig,
    HTTPFacilitatorClient,
    PaymentOption,
    x402HTTPResourceServer,
)
from x402.http.middleware.fastapi import PaymentMiddlewareASGI
from x402.http.types import (
    HTTPRequestContext,
    HTTPResponseBody,
    HTTPResponseInstructions,
    ProcessSettleResult,
    RouteConfig,
)
from x402.mechanisms.evm.exact import ExactEvmServerScheme
from x402.mechanisms.evm.utils import get_network_config
from x402.mechanisms.svm.exact import ExactSvmServerScheme
from x402.server import x402ResourceServer

from db.settings import settings


class X402Middleware:
    _x402_settlement_failure_route_fix_applied = False

    @staticmethod
    def _base64url_encode(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    @staticmethod
    def _normalize_payai_secret(secret: str) -> str:
        return secret.strip().removeprefix("payai_sk_")

    @staticmethod
    def _decode_secret_der(normalized_b64: str) -> bytes:
        for decoder in (base64.standard_b64decode, base64.urlsafe_b64decode):
            try:
                return decoder(normalized_b64)
            except binascii.Error:
                continue
        raise ValueError("PayAI API key secret is not valid base64")

    @classmethod
    def _generate_payai_jwt(cls, api_key_id: str, api_key_secret: str) -> str:
        now = int(time.time())
        header = json.dumps(
            {"alg": "EdDSA", "typ": "JWT", "kid": api_key_id},
            separators=(",", ":"),
        )
        payload = json.dumps(
            {
                "sub": api_key_id,
                "iss": "payai-merchant",
                "iat": now,
                "exp": now + 120,
                "jti": str(uuid.uuid4()),
            },
            separators=(",", ":"),
        )
        header_b64 = cls._base64url_encode(header.encode())
        payload_b64 = cls._base64url_encode(payload.encode())
        message = f"{header_b64}.{payload_b64}"
        key_bytes = cls._decode_secret_der(cls._normalize_payai_secret(api_key_secret))
        private_key = load_der_private_key(key_bytes, password=None)
        signature = private_key.sign(message.encode())
        return f"{message}.{cls._base64url_encode(signature)}"

    class CachedPayAIJwt:
        _refresh_before_expiry_sec = 30

        def __init__(self, api_key_id: str, api_key_secret: str) -> None:
            self._api_key_id = api_key_id
            self._api_key_secret = api_key_secret
            self._lock = threading.Lock()
            self._token: str | None = None
            self._refresh_at: float = 0.0

        def get(self) -> str:
            now = time.time()
            if self._token is not None and now < self._refresh_at:
                return self._token
            with self._lock:
                now = time.time()
                if self._token is not None and now < self._refresh_at:
                    return self._token
                self._token = X402Middleware._generate_payai_jwt(self._api_key_id, self._api_key_secret)
                self._refresh_at = now + (120 - self._refresh_before_expiry_sec)
                return self._token

    @classmethod
    def _apply_x402_settlement_failure_route_fix(cls) -> None:
        if cls._x402_settlement_failure_route_fix_applied:
            return

        async def _build_settlement_failure_response_async_fixed(
            self: Any,
            failure: ProcessSettleResult,
            context: HTTPRequestContext | None,
        ) -> HTTPResponseInstructions:
            settlement_headers = failure.headers
            ctx = context
            if ctx and not ctx.method:
                ctx = dataclasses.replace(ctx, method=ctx.adapter.get_method())
            route_match = self._get_route_config(ctx.path, ctx.method) if ctx else None
            route_config = route_match[0] if route_match else None
            if route_config is None and ctx:
                logging.error(
                    "x402 settlement failed (no matching route for hook): %s %s — %s",
                    ctx.method,
                    ctx.path,
                    failure.error_reason,
                )
            custom_body = None
            if route_config and route_config.settlement_failed_response_body:
                hook_result = route_config.settlement_failed_response_body(ctx, failure)
                if asyncio.iscoroutine(hook_result):
                    custom_body = await hook_result
                else:
                    custom_body = hook_result
            content_type = custom_body.content_type if custom_body else "application/json"
            body = custom_body.body if custom_body else {}
            return HTTPResponseInstructions(
                status=402,
                headers={"Content-Type": content_type, **settlement_headers},
                body=body,
                is_html=content_type.startswith("text/html"),
            )

        x402HTTPResourceServer._build_settlement_failure_response_async = (  # type: ignore[method-assign]
            _build_settlement_failure_response_async_fixed
        )
        cls._x402_settlement_failure_route_fix_applied = True
        logging.info("x402: applied settlement failure route-config tuple unpack fix")

    @staticmethod
    def _settlement_failed_response_body(
        _context: HTTPRequestContext,
        failure: ProcessSettleResult,
    ) -> HTTPResponseBody:
        detail = (failure.error_reason or "settlement failed").strip()
        logging.error("x402 settlement failed: %s", detail)
        payload: dict[str, Any] = {"error": "settlement_failed", "message": detail}
        if "): " in detail:
            tail = detail.split("): ", 1)[1].strip()
            try:
                payload["facilitator"] = json.loads(tail)
            except json.JSONDecodeError:
                payload["facilitator_raw"] = tail
        return HTTPResponseBody(content_type="application/json", body=payload)

    class SafePaymentMiddlewareASGI(PaymentMiddlewareASGI):
        @staticmethod
        def _build_facilitator_error_response(message: str) -> JSONResponse | None:
            if "Facilitator" not in message or "failed" not in message:
                return None

            payload: dict | str = {"raw": message}
            status_code = 400
            if ": " in message:
                maybe_json = message.split(": ", 1)[1]
                try:
                    parsed = json.loads(maybe_json)
                    payload = parsed
                except json.JSONDecodeError:
                    payload = {"raw": maybe_json}

            return JSONResponse(
                status_code=status_code,
                content={
                    "error": message,
                    "facilitator_response": payload,
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
                    response = self._build_facilitator_error_response(str(cur))
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
    def _resolve_bid_price(context: HTTPRequestContext) -> str:
        raw = (context.adapter.get_header("x-bid-amount") or "").strip()
        if not raw:
            raise ValueError("Missing X-Bid-Amount header")
        try:
            amount = Decimal(raw)
        except InvalidOperation as exc:
            raise ValueError("Invalid X-Bid-Amount header") from exc
        if amount <= 0:
            raise ValueError("Bid amount must be greater than zero")
        normalized = amount.quantize(Decimal("0.000001")).normalize()
        return f"${normalized:f}"

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
        base_url = settings.x402_facilitator_url.rstrip("/")
        api_id = (settings.x402_api_key or "").strip()
        api_secret = (settings.x402_api_secret or "").strip()
        if not api_id or not api_secret:
            return FacilitatorConfig(url=base_url)

        jwt_cache = X402Middleware.CachedPayAIJwt(api_id, api_secret)

        class _PayAIJwtAuthProvider(AuthProvider):
            def get_auth_headers(self) -> AuthHeaders:
                token = jwt_cache.get()
                protected = {"Authorization": f"Bearer {token}"}
                return AuthHeaders(
                    verify=protected,
                    settle=protected,
                    supported=protected,
                )

        return FacilitatorConfig(url=base_url, auth_provider=_PayAIJwtAuthProvider())

    def setup(self, app: FastAPI) -> None:
        self._apply_x402_settlement_failure_route_fix()
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
                extra={"feePayer": settings.svm_payment_addess},
            )
            for svm_network in registered_svm
        )
        if not accepts:
            fallback_network = (
                settings.x402_network
                if self._evm_supports_usdc_default(settings.x402_network)
                else "eip155:8453"
            )
            accepts = [
                PaymentOption(
                    scheme="exact",
                    pay_to=settings.evm_payment_address,
                    price=price,
                    network=fallback_network,
                )
            ]
        logging.info("accepts: %s", accepts)
        routes: dict[str, RouteConfig] = {
            "POST /backtest": RouteConfig(
                accepts=accepts,
                mime_type="application/json",
                description="Create a backtest job in queue",
                settlement_failed_response_body=self._settlement_failed_response_body,
            ),
            "POST /backtest/*/bid": RouteConfig(
                accepts=[
                    PaymentOption(
                        scheme=option.scheme,
                        pay_to=option.pay_to,
                        price=self._resolve_bid_price,
                        network=option.network,
                        extra=option.extra,
                    )
                    for option in accepts
                ],
                mime_type="application/json",
                description="Increase queue priority by paid bid amount",
                settlement_failed_response_body=self._settlement_failed_response_body,
            ),
        }

        app.add_middleware(self.SafePaymentMiddlewareASGI, routes=routes, server=server)
        app.state.x402_supported_networks = [*registered_evm, *registered_svm]
        app.state.x402_network = settings.x402_network
        app.state.x402_registered = {"evm": registered_evm, "svm": registered_svm}
