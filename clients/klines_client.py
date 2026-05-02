#!/usr/bin/env python3
# pragma python =3.13.7
# clients.klines_client
# $ python3 clients/klines_client.py

from datetime import date
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

    async def get_klines(
        self,
        start_date: date,
        end_date: date,
        symbol: str,
        *,
        exchange: str = "binance",
        timeframe: str = "1m",
        domain: str = "grindurus.xyz",
    ) -> list[str]:
        """GET /klines — список URL на суточные CSV-чанки (как в grindurus-klines-service)."""
        params: dict[str, Any] = {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "symbol": symbol,
            "exchange": exchange,
            "timeframe": timeframe,
            "domain": domain,
        }
        payload = await self.get_json("/klines", params=params)
        if not isinstance(payload, list):
            raise ValueError("Klines /klines response must be a list of URLs")
        links: list[str] = []
        for item in payload:
            if not isinstance(item, str) or not item.strip():
                raise ValueError("Klines /klines response must contain only non-empty strings")
            links.append(item.strip())
        return links


if __name__ == "__main__":
    import asyncio

    async def main():
        # Replace with your actual base_url and params as needed
        client = KlinesClient(base_url="https://klines.grindurus.xyz")
        # try:
        #     symbols = await client.get_available_symbols("binance")
        #     print("Available symbols:", symbols)
        # except Exception as e:
        #     print("Error fetching symbols:", e)
        # You can also demonstrate get_json or get_csv usage here if desired.
        # Пример: добавить вчерашний день
        from datetime import date, timedelta

        today = date.today()
        yesterday = today - timedelta(days=1)

        klines_links = await client.get_klines(
            start_date=yesterday,
            end_date=today,
            symbol="ETHUSDT",
            exchange="binance",
            timeframe="1m",
            domain="grindurus.xyz"
        )
        print(f"Klines links for {yesterday}: {klines_links}")
 

    asyncio.run(main())