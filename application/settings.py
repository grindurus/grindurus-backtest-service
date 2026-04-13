database_url: str = "postgresql+asyncpg://backtest:backtest@localhost:5432/backtest"

# ── Payment ───────────────────────────────────────────────
payment_wallet_network: str = "eip155:84532"
payment_wallet_address: str = "0x0000000000000000000000000000000000000000"
payment_token_symbol: str = "USDC"

# ── Backtest pricing (flat fee for now) ────────────────────
backtest_price: str = "1.00"

# ── Compute provider ──────────────────────────────────────
# Which provider to use:  "aws_lambda" | "local" | ...
compute_provider: str = "local"

# ── Auth (placeholder — add JWT / API-key auth later) ─────
webhook_backtest_secret: str = "change-me-in-production"

api_base_url: str = "http://localhost:8000"

app_mode = "test"