"""
Backward-compatible settings exports.

Use `db.config.get_settings()` for new code.
"""

from db.config import get_settings

_settings = get_settings()

database_url: str = _settings.database_url
payment_wallet_network: str = _settings.payment_wallet_network
payment_wallet_address: str = _settings.payment_wallet_address
payment_token_symbol: str = _settings.payment_token_symbol
backtest_price: str = _settings.backtest_price
compute_provider: str = _settings.compute_provider
webhook_backtest_secret: str = _settings.webhook_backtest_secret
api_base_url: str = _settings.api_base_url
app_mode: str = _settings.app_mode
