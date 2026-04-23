from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class PaymentConfirmedWebhook(BaseModel):
    job_id: str
    tx_hash: str
    amount: str
    token: str
    confirmations: int = 1


class BacktestCompleteWebhook(BaseModel):
    job_id: str
    success: bool
    result: dict[str, Any] | None = None
    error_message: str | None = None
