from __future__ import annotations

from typing import Any

from aiohttp import ClientError, ClientTimeout

from .domain.open_meteo import (
    air_quality_url_params,
    forecast_url_params,
    map_air_quality_response,
    map_forecast_response,
)

_TIMEOUT = ClientTimeout(total=30)


class OpenMeteoClient:
    """Fetch Open-Meteo forecast and air-quality data as collector payloads."""

    def __init__(self, session: Any) -> None:
        self._session = session

    async def _get_json(
        self, url: str, params: dict[str, Any]
    ) -> tuple[int, Any]:
        query = {key: str(value) for key, value in params.items()}
        async with self._session.get(url, params=query, timeout=_TIMEOUT) as response:
            status = response.status
            if status >= 400:
                return status, {}
            return status, await response.json(content_type=None)

    async def fetch_forecast(self, request: Any) -> dict[str, Any]:
        """Return a collector-shaped forecast payload, backing off on failure."""
        try:
            status, body = await self._get_json(*forecast_url_params(request))
        except ClientError:
            return {"status": 503}
        return map_forecast_response(body, status)

    async def fetch_air_quality(self, request: Any) -> dict[str, Any]:
        """Return a collector-shaped air-quality payload, backing off on failure."""
        try:
            status, body = await self._get_json(*air_quality_url_params(request))
        except ClientError:
            return {"status": 503}
        return map_air_quality_response(body, status)
