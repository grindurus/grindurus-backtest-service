from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://backtest:backtest@localhost:5432/backtest"
    payment_wallet_network: str = "eip155:84532"
    payment_wallet_address: str = "0x0000000000000000000000000000000000000000"
    payment_token_symbol: str = "USDC"
    backtest_price: str = "1.00"
    compute_provider: str = "local"
    webhook_backtest_secret: str = "change-me-in-production"
    api_base_url: str = "http://localhost:8000"
    app_mode: str = "test"


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    return AppSettings()
