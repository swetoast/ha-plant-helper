"""iNaturalist enrichment provider for Plant Helper."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import aiohttp

from .base import ProviderResult, RateLimiter

_LOGGER = logging.getLogger(__name__)


class INaturalistProvider:
    """Optional iNaturalist observations/photo enrichment."""

    def __init__(
        self,
        *,
        session: aiohttp.ClientSession,
        enabled: bool = True,
        daily_limit: int = 300,
        min_interval_seconds: int = 3,
    ) -> None:
        """Initialize provider."""
        self.session = session
        self.enabled = enabled
        self.base_url = "https://api.inaturalist.org/v1"
        self.limiter = RateLimiter(daily_limit=daily_limit, min_interval_seconds=min_interval_seconds)
        self.last_error: str | None = None
        self.last_success: str | None = None

    async def enrich(self, plant_data: dict[str, Any]) -> ProviderResult:
        """Enrich an already identified plant with iNaturalist observations."""
        if not self.enabled:
            return ProviderResult(False, "inaturalist", api_checked=False, api_called=False, message="iNaturalist enrichment disabled")
        if not self.limiter.can_call():
            return ProviderResult(False, "inaturalist", api_checked=True, api_called=False, message="iNaturalist limit reached or interval not ready")

        query = plant_data.get("scientific_name") or plant_data.get("common_name") or plant_data.get("species")
        if not query:
            return ProviderResult(False, "inaturalist", api_checked=False, api_called=False, message="No query available for iNaturalist")

        try:
            params: dict[str, Any] = {
                "iconic_taxa": "Plantae",
                "photos": "true",
                "quality_grade": "research",
                "per_page": 5,
                "page": 1,
            }
            if plant_data.get("scientific_name"):
                params["taxon_name"] = plant_data["scientific_name"]
            else:
                params["q"] = query

            payload = await self._get_json(f"{self.base_url}/observations", params)
            if payload is None:
                return ProviderResult(False, "inaturalist", api_checked=True, api_called=True, calls_made=1, message=self.last_error or "iNaturalist request failed")

            results = payload.get("results") or []
            enrichment = self._normalize(payload, query)
            self.last_error = None
            self.last_success = datetime.now().isoformat()
            return ProviderResult(bool(results), "inaturalist", data=enrichment, api_checked=True, api_called=True, calls_made=1, message=f"iNaturalist returned {len(results)} observations")

        except Exception as err:
            _LOGGER.exception("iNaturalist enrichment failed for %s", query)
            self.last_error = str(err)
            return ProviderResult(False, "inaturalist", api_checked=True, api_called=True, message=f"iNaturalist error: {err}")

    async def _get_json(self, url: str, params: dict[str, Any]) -> dict[str, Any] | None:
        """GET JSON from iNaturalist."""
        if not self.limiter.can_call():
            self.last_error = "iNaturalist limit reached"
            return None
        self.limiter.mark_call()
        async with self.session.get(url, params=params, timeout=10) as response:
            if response.status != 200:
                text = await response.text()
                self.last_error = f"iNaturalist HTTP {response.status}: {text[:200]}"
                return None
            return await response.json()

    def _normalize(self, payload: dict[str, Any], query: str) -> dict[str, Any]:
        """Normalize iNaturalist observations."""
        results = payload.get("results") or []
        observations: list[dict[str, Any]] = []
        photos: list[dict[str, Any]] = []

        for item in results[:5]:
            obs = {
                "id": item.get("id"),
                "uri": item.get("uri"),
                "observed_on": item.get("observed_on"),
                "place_guess": item.get("place_guess"),
                "quality_grade": item.get("quality_grade"),
                "taxon": (item.get("taxon") or {}).get("name"),
                "preferred_common_name": (item.get("taxon") or {}).get("preferred_common_name"),
            }
            observations.append(obs)
            for photo in item.get("photos") or []:
                url = photo.get("url") or photo.get("medium_url") or photo.get("square_url")
                if url:
                    photos.append({
                        "url": url,
                        "license_code": photo.get("license_code"),
                        "attribution": photo.get("attribution"),
                        "observation_id": item.get("id"),
                    })

        return {
            "provider": "inaturalist",
            "query": query,
            "observations_checked": True,
            "observation_count": payload.get("total_results", len(results)),
            "returned_observations": len(results),
            "observations": observations,
            "photos": photos[:10],
            "updated_at": datetime.now().isoformat(),
        }
