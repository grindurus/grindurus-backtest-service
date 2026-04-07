"""
Compute provider abstraction.

The backend doesn't care *where* the backtest runs — only that it can
dispatch a job and get a callback when it's done.

To add a new provider:
  1. Subclass ComputeProvider
  2. Implement dispatch()
  3. Register it in get_compute_provider()
"""

from __future__ import annotations

import abc
import asyncio
import json
import logging
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class ComputeProvider(abc.ABC):
    """
    Interface for anything that can run a backtest.
    """

    @abc.abstractmethod
    async def dispatch(self, job_id: str, params: dict[str, Any]) -> None:
        """
        Fire-and-forget: launch the backtest.
        The provider MUST call back to POST /webhooks/backtest-complete
        when the work is finished (success or failure).
        """
        ...


# ── AWS Lambda via SQS ────────────────────────────────────────
class AwsLambdaProvider(ComputeProvider):
    """
    Pushes a message onto an SQS queue.
    A separate SQS → Lambda trigger picks it up and invokes the function.
    """

    async def dispatch(self, job_id: str, params: dict[str, Any]) -> None:
        # boto3 is synchronous — run in a thread so we don't block the event loop
        import boto3

        def _send() -> None:
            sqs = boto3.client("sqs", region_name=settings.aws_region)
            sqs.send_message(
                QueueUrl=settings.aws_sqs_queue_url,
                MessageBody=json.dumps({
                    "job_id": job_id,
                    "params": params,
                    "callback_url": f"{settings.api_base_url}/webhooks/backtest-complete",
                }),
                MessageGroupId="backtest",  # if using FIFO queue
            )
            logger.info("SQS message sent for job %s", job_id)

        await asyncio.to_thread(_send)


# ── Local / dev provider ──────────────────────────────────────
class LocalProvider(ComputeProvider):
    """
    Dev-mode provider that fakes a backtest by sleeping, then
    calling the webhook endpoint on localhost.
    """

    async def dispatch(self, job_id: str, params: dict[str, Any]) -> None:
        logger.info("LocalProvider: dispatching job %s (fake 3s delay)", job_id)

        async def _simulate() -> None:
            await asyncio.sleep(3)  # simulate work
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"{settings.api_base_url}/webhooks/backtest-complete",
                    json={
                        "job_id": job_id,
                        "success": True,
                        "result": {
                            "sharpe_ratio": 1.42,
                            "total_return_pct": 23.7,
                            "max_drawdown_pct": -8.1,
                            "total_trades": 147,
                            "win_rate_pct": 58.5,
                            "note": "This is simulated data from LocalProvider",
                        },
                    },
                    headers={"X-Webhook-Secret": settings.webhook_backtest_secret},
                )
            logger.info("LocalProvider: callback sent for job %s", job_id)

        # fire-and-forget (don't await — return immediately)
        asyncio.create_task(_simulate())


# ── Factory ───────────────────────────────────────────────────
_PROVIDERS: dict[str, type[ComputeProvider]] = {
    "aws_lambda": AwsLambdaProvider,
    "local": LocalProvider,
}


def get_compute_provider() -> ComputeProvider:
    """Return the configured compute provider instance."""
    cls = _PROVIDERS.get(settings.compute_provider)
    if cls is None:
        raise ValueError(
            f"Unknown compute_provider={settings.compute_provider!r}. "
            f"Available: {list(_PROVIDERS.keys())}"
        )
    return cls()