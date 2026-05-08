#!/usr/bin/env python3
# pragma python =3.13.7
# clients.boss_client
# $ python3 clients/boss_client.py

import json
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator
from urllib.parse import parse_qs, urlparse

import httpx


class BossClient:
    """HTTPS adapter for communication with Boss service."""

    def __init__(
        self,
        base_url: str,
        x_boss_key: str | None = None,
        x_grind_key: str | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.x_boss_key = x_boss_key
        self.x_grind_key = x_grind_key
        self.timeout_seconds = timeout_seconds

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.x_boss_key:
            headers["x-boss-key"] = self.x_boss_key
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
        adapter_init: dict[str, Any] | None = None,
        backtest_init: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
        direct_grindurus_data: dict[str, Any] | None = None,
        inverse_grindurus_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        adapter_dict: dict[str, Any] = {
            "terminal": terminal,
            "adapter_init": adapter_init,
            "backtest_init": backtest_init,
            "config": config,
        }
        adapter_dict = {k: v for k, v in adapter_dict.items() if v is not None}
        init_payload: dict[str, Any] = {
            "adapter_dict": adapter_dict,
            "grinder_data": {
                "loop_period": 1.0,
                "target_nav": 0.0,
                "big": 25,
                "small": 125,
            },
            "direct_grindurus_data": direct_grindurus_data,
            "inverse_grindurus_data": inverse_grindurus_data,
        }
        init_payload = {k: v for k, v in init_payload.items() if v is not None}
        return await self.post(f"/grinder/{grinder_id}/init", init_payload)

    async def start(self, grinder_id: str) -> dict[str, Any]:
        return await self.post(f"/grinder/{grinder_id}/start", {})

    async def stop(self, grinder_id: str) -> dict[str, Any]:
        return await self.post(f"/grinder/{grinder_id}/stop", {})

    async def info(self, grinder_id: str, verbose=0) -> dict[str, Any]:
        return await self.get(f"grinder/{grinder_id}/info?verbose={verbose}", {})

    async def logs(
        self,
        grinder_id: str,
        *,
        stop_at_utc: datetime | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        url = f"{self.base_url}/grinder/{grinder_id}/logs/stream"
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("GET", url, headers=self._headers()) as response:
                self._raise_for_status(response)
                buffer = ""
                async for chunk in response.aiter_text():
                    if not chunk:
                        continue
                    buffer += chunk
                    while "\n\n" in buffer:
                        event, buffer = buffer.split("\n\n", 1)
                        data_lines = [
                            line[6:]
                            for line in event.splitlines()
                            if line.startswith("data: ")
                        ]
                        if not data_lines:
                            continue
                        payload_text = "\n".join(data_lines).strip()
                        if not payload_text:
                            continue
                        try:
                            payload_data = json.loads(payload_text)
                            yield payload_data
                            if stop_at_utc is not None and isinstance(payload_data, dict):
                                time_raw = payload_data.get("time")
                                if isinstance(time_raw, str):
                                    try:
                                        payload_time = datetime.fromisoformat(time_raw.replace("Z", "+00:00"))
                                        print(f"{payload_time} < {stop_at_utc}")
                                    except ValueError:
                                        payload_time = None
                                    if payload_time is not None:
                                        if payload_time.tzinfo is None:
                                            payload_time = payload_time.replace(tzinfo=timezone.utc)
                                        if payload_time >= stop_at_utc:
                                            print("WTF")
                                            return
                        except json.JSONDecodeError:
                            yield {"raw": payload_text}

    async def deconstruct(self, grinder_id: str) -> dict[str, Any]:
        return await self.post(f"/grinder/{grinder_id}/deconstruct", {})

    async def backtest(
        self,
        grinder_id: str,
        terminal: str,
        backtest_init: dict[str, Any],
        *,
        stop_at_utc: datetime | None = None,
        print_logs: bool = True,
    ) -> dict[str, Any]:
        if stop_at_utc is None:
            end_time_utc = self._parse_end_time_from_paths(backtest_init.get("paths", []))
            stop_at_utc = end_time_utc - timedelta(minutes=5) if end_time_utc is not None else None

        pre_deconstruct_result: dict[str, Any]
        try:
            pre_deconstruct_result = await self.deconstruct(grinder_id)
        except httpx.HTTPStatusError as exc:
            body = self._format_error_body(exc.response)
            if exc.response.status_code == 400 and "'NoneType' object has no attribute 'deconstruct'" in body:
                pre_deconstruct_result = {"result": "already_deconstructed"}
            else:
                raise

        init_result = await self.init_grinder(
            grinder_id=grinder_id,
            terminal=terminal,
            backtest_init=backtest_init,
        )
        start_result = await self.start(grinder_id)

        logs: list[dict[str, Any]] = []
        async for log_event in self.logs(grinder_id, stop_at_utc=stop_at_utc):
            logs.append(log_event)
            if print_logs:
                print(log_event)

        stop_result = await self.stop(grinder_id)
        info_result = await self.info(grinder_id)
        deconstruct_result = await self.deconstruct(grinder_id)

        return {
            "pre_deconstruct": pre_deconstruct_result,
            "init": init_result,
            "start": start_result,
            "logs": logs,
            "stop": stop_result,
            "info": info_result,
            "deconstruct": deconstruct_result,
            "stop_at_utc": stop_at_utc.isoformat() if stop_at_utc is not None else None,
        }
    
    def _parse_end_time_from_paths(self, paths: list[str]) -> datetime | None:
        if not paths:
            return None
        raw = parse_qs(urlparse(paths[-1]).query).get("end_time", [None])[-1]
        if not raw:
            return None
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if len(raw) == 10:
            dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        return dt

if __name__ == "__main__":
    import asyncio, os
    from dotenv import load_dotenv
    load_dotenv()
    x_boss_key = os.getenv('X_BOSS_KEY')
    x_grind_key = os.getenv('X_GRIND_KEY')
    
    async def main():
        client = BossClient(
            base_url="https://backboss.grindurus.xyz",
            x_boss_key=x_boss_key,
            x_grind_key=x_grind_key,
        )
        try:
            result = await client.get("health")
            print("Health:", result)
        except Exception as e:
            print("Error:", e)
        grinder_id: str = "1"
        backtest_init = {
            'paths': [
                'https://klines.grindurus.xyz/klines.csv?start_time=2026-05-01&end_time=2026-05-02&exchange=binance&symbol=ETHUSDT&timeframe=1m',
            ],
            'base_balance': '0.0',
            'quote_balance': '10000.0',
        }
        result = await client.backtest(
            grinder_id=grinder_id,
            terminal="binance",
            backtest_init=backtest_init,
            print_logs=True,
        )
        print("\nInit Grinder Result:", result["init"])
        print("\nStart Result:", result["start"])
        print("\nStop Result:", result["stop"])
        print("\nInfo Result:", result["info"])
        print("\nDeconstruct Result:", result["deconstruct"])

    asyncio.run(main())
