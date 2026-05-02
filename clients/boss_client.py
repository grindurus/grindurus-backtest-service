#!/usr/bin/env python3
# pragma python =3.13.7
# clients.boss_client
# $ python3 clients/boss_client.py

import json
from typing import Any

import httpx


class BossClient:
    """HTTPS adapter for communication with Boss service."""

    def __init__(
        self,
        base_url: str,
        x_grind_key: str | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.x_grind_key = x_grind_key
        self.timeout_seconds = timeout_seconds

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.x_grind_key:
            headers["x-grind-key"] = self.x_grind_key
        return headers

    @staticmethod
    def _format_error_body(response: httpx.Response, max_len: int = 8000) -> str:
        text = response.text.strip()
        if not text:
            return "(empty body)"
        try:
            parsed = response.json()
            text = json.dumps(parsed, ensure_ascii=False, indent=2)
        except (ValueError, json.JSONDecodeError):
            pass
        if len(text) > max_len:
            return f"{text[:max_len]}... (truncated, total {len(response.text)} chars)"
        return text

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            body = BossClient._format_error_body(exc.response)
            raise httpx.HTTPStatusError(
                f"{exc}\n--- response body ---\n{body}",
                request=exc.request,
                response=exc.response,
            ) from exc

    async def post(self, endpoint: str, payload: dict[str, Any] | str) -> dict[str, Any]:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        if isinstance(payload, str):
            body = payload.encode("utf-8")
        else:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(url, content=body, headers=self._headers())
            self._raise_for_status(response)
            return response.json()

    async def get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.get(url, params=params, headers=self._headers())
            self._raise_for_status(response)
            return response.json()

    @staticmethod
    def _grindurus_json_value(value: dict[str, Any] | None) -> Any:
        if value is None or value == {}:
            return None
        return value

    async def init_grinder(
        self,
        grinder_id: str,
        terminal: str,
        *,
        backtest_init: dict[str, Any],
        adapter_init: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
        direct_grindurus_dict: dict[str, Any] | None = None,
        inverse_grindurus_dict: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        adapter_dict: dict[str, Any] = {
            "terminal": terminal,
            "backtest_init": backtest_init,
        }
        if adapter_init is not None:
            adapter_dict["adapter_init"] = adapter_init
        if config is not None:
            adapter_dict["config"] = config

        payload: dict[str, Any] = {
            "adapter_dict": adapter_dict,
            "direct_grindurus_dict": self._grindurus_json_value(direct_grindurus_dict),
            "inverse_grindurus_dict": self._grindurus_json_value(inverse_grindurus_dict),
        }
        return await self.post(f"/grinder/{grinder_id}/init", payload)


if __name__ == "__main__":
    import asyncio

    # Example usage
    async def main():
        client = BossClient(
            base_url="https://backboss.grindurus.xyz",
            x_grind_key="1qazZAQ!",
        )
        try:
            result = await client.get("health")
            print("Health:", result)
        except Exception as e:
            print("Error:", e)
        # Example call to init_grinder()
        # Provide dummy/sample parameters for illustration
        backtest_init = {
            'paths': [
                'https://klines.grindurus.xyz/klines.csv?start_time=2026-05-01&end_time=2026-05-02&exchange=binance&symbol=ETHUSDT&timeframe=1m',
            ],
            'base_balance': '0.0',
            'quote_balance': '10000.0',
        }
        grinder_result = await client.init_grinder(
            grinder_id="1",
            terminal="binance",
            backtest_init=backtest_init,
        )
        print("Init Grinder Result:", grinder_result)

    asyncio.run(main())
