"""
Centralised configuration.  Every value comes from an env var (or .env file).
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── Postgres ──────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://backtest:backtest@localhost:5432/backtest"

    # ── Payment ───────────────────────────────────────────────
    # The wallet address users pay to.  In production this might be
    # generated per-job; for now one static address is fine.
    payment_wallet_network: str = "eip155:84532"
    payment_wallet_address: str = "0x0000000000000000000000000000000000000000"
    payment_token_symbol: str = "USDC"
    # How many block confirmations before we trust a payment
    payment_required_confirmations: int = 2
    # Webhook secret shared with the payment listener (Alchemy, etc.)
    payment_webhook_secret: str = "change-me-in-production"

    # ── Backtest pricing (flat fee for now) ────────────────────
    backtest_price_amount: str = "1.00"

    # ── Compute provider ──────────────────────────────────────
    # Which provider to use:  "aws_lambda" | "local" | ...
    compute_provider: str = "local"

    # AWS-specific (only used when compute_provider == "aws_lambda")
    aws_lambda_function_name: str = "backtest-runner"
    aws_region: str = "us-east-1"
    aws_sqs_queue_url: str = ""

    # ── Webhook callback base URL (so the worker can call us back) ─
    api_base_url: str = "http://localhost:8000"

    # ── Auth (placeholder — add JWT / API-key auth later) ─────
    webhook_backtest_secret: str = "change-me-in-production"

    model_config = {"env_prefix": "BT_", "env_file": ".env", "extra": "ignore"}


settings = Settings()