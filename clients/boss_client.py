from __future__ import annotations

from typing import Any

import httpx


class BossClient:
    """HTTPS adapter for communication with Boss service."""

    def __init__(
        self,
        base_url: str,
        api_token: str | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token
        self.timeout_seconds = timeout_seconds

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        return headers

    async def post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(url, json=payload, headers=self._headers())
            response.raise_for_status()
            return response.json()

    async def get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.get(url, params=params, headers=self._headers())
            response.raise_for_status()
            return response.json()
