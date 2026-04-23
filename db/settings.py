from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_mode: str = "dev"
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/backtests"
    payment_wallet_address: str = "0xC185CDED750dc34D1b289355Fe62d10e86BEDDee"
    backtest_price: str = "1"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
