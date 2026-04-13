from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

import application.settings as settings
from application.database import get_db
from application.schemas import BacktestCompleteWebhook, PaymentConfirmedWebhook
from application import job_service

router = APIRouter(prefix="/webhooks", tags=["webhooks"])



def _verify_backtest_secret(x_webhook_secret: str = Header(...)) -> None:
    if x_webhook_secret != settings.webhook_backtest_secret:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")


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