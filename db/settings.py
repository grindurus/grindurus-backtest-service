from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_mode: str = "dev"
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/backtests"
    evm_payment_address: str = "0xDEC67cDDeCffdf6f45E7bC221D404eE87A720380"
    svm_payment_addess: str = "tUGZcHD5iJfpWemXGirf4Mh8pyYa8SoaWKPmxPMgwYC"
    backtest_price: str = "$0.01"
    x402_facilitator_url: str = "https://facilitator.x402endpoints.online"
    x402_api_key: str = ""
    x402_network: str = "eip155:8453"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
