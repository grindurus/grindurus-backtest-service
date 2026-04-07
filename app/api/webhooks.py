"""
Webhook endpoints — called by external services, not the frontend.

/webhooks/payment-confirmed   ← blockchain listener / x402 callback
/webhooks/backtest-complete   ← compute worker (Lambda / Cloud Run / etc.)

Both are protected by a shared secret in the X-Webhook-Secret header.
In production you'd use HMAC signatures; this is a reasonable starting point.
"""

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.schemas.backtest import BacktestCompleteWebhook, PaymentConfirmedWebhook
from app.services import job_service

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


# ── Helpers ───────────────────────────────────────────────────
def _verify_payment_secret(x_webhook_secret: str = Header(...)) -> None:
    if x_webhook_secret != settings.payment_webhook_secret:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")


def _verify_backtest_secret(x_webhook_secret: str = Header(...)) -> None:
    if x_webhook_secret != settings.webhook_backtest_secret:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")


# ── Payment confirmed ─────────────────────────────────────────
@router.post(
    "/payment-confirmed",
    status_code=200,
    summary="Payment confirmed callback",
    dependencies=[Depends(_verify_payment_secret)],
)
async def payment_confirmed(
    body: PaymentConfirmedWebhook,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Called when the blockchain listener (Alchemy, your node, x402)
    detects a confirmed payment for a job.

    Side effects:
      - job → payment_confirmed → queued
      - dispatches to compute provider
    """
    try:
        job = await job_service.confirm_payment(db, body.job_id, body.tx_hash)
    except job_service.JobError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {"job_id": job.id, "status": job.status.value}


# ── Backtest complete ─────────────────────────────────────────
@router.post(
    "/backtest-complete",
    status_code=200,
    summary="Backtest result callback",
    dependencies=[Depends(_verify_backtest_secret)],
)
async def backtest_complete(
    body: BacktestCompleteWebhook,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Called by the compute worker when the backtest finishes
    (success or failure).
    """
    try:
        if body.success and body.result is not None:
            job = await job_service.complete_job(db, body.job_id, body.result)
        else:
            job = await job_service.fail_job(
                db,
                body.job_id,
                body.error_message or "Unknown error from compute worker",
            )
    except job_service.JobError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {"job_id": job.id, "status": job.status.value}