from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ── Request: create a backtest job ────────────────────────────
class BacktestCreateRequest(BaseModel):
    """
    The frontend sends strategy parameters.
    We don't validate the inner structure — the backtest engine will.
    """
    params: dict[str, Any] = Field(
        ...,
        description="Arbitrary strategy / backtest parameters (forwarded to engine)",
        examples=[{
            "strategy": "GrindURUS",
            "symbol": "ETH-USD",
            "start_date": "2025-01-01",
            "end_date": "2025-12-31",
            "timeframe": "1h",
            "initial_capital": 10000,
        }],
    )
    # Optional: let the user attach a wallet address for ownership tracking
    owner_address: str | None = Field(
        None,
        description="Wallet address of the requester (for lookup later)",
    )


# ── Response: job created (tells frontend how to pay) ─────────
class BacktestCreateResponse(BaseModel):
    job_id: str
    status: str
    message: str = "Send payment to proceed. Poll GET /jobs/{job_id} for status."


# ── Response: job status (used by polling endpoint) ───────────
class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    created_at: datetime
    updated_at: datetime

    # Only populated when status == "done"
    result: dict[str, Any] | None = None
    # Only populated when status == "failed"
    error_message: str | None = None

    # Payment info (so frontend can show tx link)
    payment_tx_hash: str | None = None


# ── Webhook: payment confirmed ────────────────────────────────
class PaymentConfirmedWebhook(BaseModel):
    """
    Sent by the blockchain listener (Alchemy, your indexer, x402 callback).
    """
    job_id: str
    tx_hash: str
    amount: str
    token: str
    confirmations: int = 1


# ── Webhook: backtest complete (from the compute worker) ──────
class BacktestCompleteWebhook(BaseModel):
    job_id: str
    success: bool
    result: dict[str, Any] | None = None
    error_message: str | None = None