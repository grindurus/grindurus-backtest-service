from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_mode: str = "dev"
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/backtests"
    evm_payment_address: str = "0xDEC67cDDeCffdf6f45E7bC221D404eE87A720380"
    svm_payment_addess: str = "5fKqJxRfvqMuTKxAbyom2iz1sexrpRFoQmTCzyffFyiV"
    backtest_price: str = "$0.01"
    x402_facilitator_url: str = "https://facilitator.payai.network"
    x402_api_key: str = ""
    x402_api_secret: str = ""
    # PayAI merchant: API Key ID (kid) + PKCS#8 secret (payai_sk_...); see PayAI facilitator auth.
    x402_network_fallback: str = "eip155:8453"
    x_admin_key: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
