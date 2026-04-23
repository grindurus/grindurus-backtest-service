from __future__ import annotations

from x402 import x402ResourceServer
from x402.http import FacilitatorConfig, HTTPFacilitatorClient, PaymentOption
from x402.http.middleware.fastapi import PaymentMiddlewareASGI
from x402.http.types import RouteConfig
from x402.mechanisms.evm.exact import ExactEvmServerScheme

from db import settings
from payments.PaymentAdapter import MiddlewareSpec, PaymentAdapter


class X402PaymentAdapter(PaymentAdapter):
    def get_middleware_specs(self) -> list[MiddlewareSpec]:
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
        return [
            MiddlewareSpec(
                middleware_cls=PaymentMiddlewareASGI,
                kwargs={"routes": routes, "server": server},
            )
        ]
