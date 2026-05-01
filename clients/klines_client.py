from __future__ import annotations

from typing import Any
import time

import httpx


class KlinesClient:
    """HTTPS adapter for communication with Klines service."""

    def __init__(
        self,
        base_url: str = "https://klines.grindurus.xyz",
        timeout_seconds: float = 30.0,
        symbols_cache_ttl_seconds: float = 300.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.symbols_cache_ttl_seconds = max(0.0, symbols_cache_ttl_seconds)
        self._symbols_cache: dict[str, tuple[float, dict[str, list[str]]]] = {}

    async def get_json(self, endpoint: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()

    async def get_csv(self, endpoint: str, params: dict[str, Any] | None = None) -> str:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.text

    async def get_available_symbols(self, exchange: str = "binance") -> dict[str, list[str]]:
        cache_key = exchange.strip().lower() or "binance"
        now = time.monotonic()
        cached_entry = self._symbols_cache.get(cache_key)
        if cached_entry is not None:
            cached_at, cached_symbols = cached_entry
            if now - cached_at <= self.symbols_cache_ttl_seconds:
                return cached_symbols

        payload = await self.get_json("/symbols", params={"exchange": cache_key})
        if not isinstance(payload, dict):
            raise ValueError("Klines /symbols response must be an object")

        normalized: dict[str, list[str]] = {}
        for base_asset, quote_assets in payload.items():
            if not isinstance(base_asset, str) or not base_asset:
                continue
            if not isinstance(quote_assets, (list, tuple, set)):
                continue

            cleaned_quotes = sorted(
                {
                    str(quote).strip().upper()
                    for quote in quote_assets
                    if isinstance(quote, str) and quote.strip()
                }
            )
            if cleaned_quotes:
                normalized[base_asset.strip().upper()] = cleaned_quotes

        if not normalized:
            raise ValueError("Klines /symbols response is empty or invalid")
        self._symbols_cache[cache_key] = (now, normalized)
        return normalized
