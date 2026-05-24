"""Perenual API provider for Plant Helper."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import aiohttp

from .base import ProviderResult, RateLimiter, first_value, normalize_text

_LOGGER = logging.getLogger(__name__)

PERENUAL_DAILY_LIMIT = 100


class PerenualProvider:
    """Perenual plant data provider."""

    def __init__(
        self,
        *,
        session: aiohttp.ClientSession,
        api_key: str | None,
        daily_limit: int = PERENUAL_DAILY_LIMIT,
    ) -> None:
        """Initialize provider."""
        self.session = session
        self.api_key = api_key or ""
        self.base_url = "https://perenual.com/api"
        self.limiter = RateLimiter(daily_limit=daily_limit)
        self.last_error: str | None = None
        self.last_success: str | None = None

    async def fetch(
        self,
        search_name: str,
        *,
        fetch_care_guides: bool = True,
        fetch_diseases: bool = True,
    ) -> ProviderResult:
        """Fetch plant data from Perenual."""
        if not self.api_key:
            return ProviderResult(False, "perenual", api_checked=True, api_called=False, message="Perenual API key missing")

        if not self.limiter.can_call():
            self.last_error = "Perenual daily limit reached or call interval not ready"
            return ProviderResult(False, "perenual", api_checked=True, api_called=False, message=self.last_error)

        try:
            payload = await self._get_json(
                f"{self.base_url}/v2/species-list",
                {"key": self.api_key, "q": search_name, "page": 1},
            )
            if payload is None:
                return ProviderResult(False, "perenual", api_checked=True, api_called=True, calls_made=1, message=self.last_error or "Perenual search failed")

            results = payload.get("data") or []
            if not results:
                return ProviderResult(False, "perenual", api_checked=True, api_called=True, calls_made=1, message="Perenual returned no results")

            selected = self._select_best(search_name, results)
            if not selected:
                return ProviderResult(False, "perenual", api_checked=True, api_called=True, calls_made=1, message="No usable Perenual match")

            calls = 1
            species_id = selected.get("id")
            detail = selected

            if species_id:
                detail_payload = await self._get_json(
                    f"{self.base_url}/v2/species/details/{species_id}",
                    {"key": self.api_key},
                )
                calls += 1
                if detail_payload:
                    detail = detail_payload

            care_guides = None
            diseases = None

            if species_id and fetch_care_guides:
                care_guides = await self._get_json(
                    f"{self.base_url}/species-care-guide-list",
                    {"key": self.api_key, "species_id": species_id, "page": 1},
                )
                calls += 1

            if fetch_diseases:
                diseases = await self._get_json(
                    f"{self.base_url}/pest-disease-list",
                    {"key": self.api_key, "q": search_name, "page": 1},
                )
                calls += 1

            data = self._normalize_plant(detail, care_guides=care_guides, diseases=diseases)
            self.last_error = None
            self.last_success = datetime.now().isoformat()

            return ProviderResult(True, "perenual", data=data, api_checked=True, api_called=True, calls_made=calls, message="Perenual match found")

        except Exception as err:
            _LOGGER.exception("Perenual lookup failed for %s", search_name)
            self.last_error = str(err)
            return ProviderResult(False, "perenual", api_checked=True, api_called=True, message=f"Perenual error: {err}")

    async def _get_json(self, url: str, params: dict[str, Any]) -> dict[str, Any] | None:
        """GET JSON and track limits."""
        if not self.limiter.can_call():
            self.last_error = "Perenual limit reached"
            return None

        self.limiter.mark_call()

        async with self.session.get(url, params=params, timeout=10) as response:
            if response.status == 429:
                self.last_error = "Perenual rate limit reached"
                return None
            if response.status != 200:
                text = await response.text()
                self.last_error = f"Perenual HTTP {response.status}: {text[:200]}"
                return None
            return await response.json()

    def _select_best(self, search_name: str, results: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Select best Perenual result."""
        search = normalize_text(search_name)
        for item in results:
            if normalize_text(item.get("common_name")) == search:
                return item
        for item in results:
            if search in normalize_text(item.get("common_name")):
                return item
            for other in item.get("other_name") or []:
                if normalize_text(other) == search:
                    return item
        return results[0] if results else None

    def _normalize_plant(
        self,
        data: dict[str, Any],
        *,
        care_guides: dict[str, Any] | None,
        diseases: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Normalize Perenual data."""
        scientific_name = first_value(data.get("scientific_name"))
        species = scientific_name or data.get("species") or data.get("common_name")
        common_name = data.get("common_name") or species

        return {
            "species": species,
            "common_name": common_name,
            "scientific_name": scientific_name,
            "other_name": data.get("other_name", []),
            "family": data.get("family"),
            "genus": data.get("genus"),
            "cycle": data.get("cycle"),
            "care_level": data.get("care_level"),
            "watering": data.get("watering"),
            "sunlight": data.get("sunlight", []),
            "soil": data.get("soil", []),
            "maintenance": data.get("maintenance"),
            "growth_rate": data.get("growth_rate"),
            "description": data.get("description"),
            "poisonous_to_humans": data.get("poisonous_to_humans"),
            "poisonous_to_pets": data.get("poisonous_to_pets"),
            "pest_susceptibility": data.get("pest_susceptibility", []),
            "flowering_season": data.get("flowering_season"),
            "pruning_month": data.get("pruning_month", []),
            "default_image": data.get("default_image"),
            "thresholds": self._thresholds(data),
            "tips": self._tips(data, care_guides),
            "facts": self._facts(data),
            "common_diseases": self._diseases(diseases),
            "source": "perenual",
            "provider": "perenual",
            "provider_id": data.get("id"),
            "updated_at": datetime.now().isoformat(),
        }

    def _thresholds(self, data: dict[str, Any]) -> dict[str, Any]:
        """Build thresholds from Perenual."""
        watering = str(data.get("watering") or "").lower()
        if watering == "minimum":
            return {"soil_moisture_min": 15, "soil_moisture_max": 45}
        if watering == "average":
            return {"soil_moisture_min": 25, "soil_moisture_max": 65}
        if watering == "frequent":
            return {"soil_moisture_min": 40, "soil_moisture_max": 80}
        return {}

    def _tips(self, data: dict[str, Any], care_guides: dict[str, Any] | None) -> dict[str, list[str]]:
        """Build tips."""
        direct: list[str] = []
        seasonal: list[str] = []
        if data.get("watering"):
            direct.append(f"Watering: {data['watering']}")
        sunlight = data.get("sunlight")
        if sunlight:
            direct.append("Sunlight: " + (", ".join(sunlight) if isinstance(sunlight, list) else str(sunlight)))
        if care_guides:
            for guide in care_guides.get("data", []):
                for section in guide.get("section") or []:
                    if section.get("description"):
                        direct.append(section["description"])
        return {"direct": list(dict.fromkeys(direct)), "seasonal": seasonal}

    def _facts(self, data: dict[str, Any]) -> list[str]:
        """Build facts."""
        facts: list[str] = []
        for key, label in (("family", "Family"), ("genus", "Genus"), ("cycle", "Cycle"), ("care_level", "Care level"), ("maintenance", "Maintenance"), ("growth_rate", "Growth rate")):
            if data.get(key):
                facts.append(f"{label}: {data[key]}")
        return facts

    def _diseases(self, diseases: dict[str, Any] | None) -> list[dict[str, Any]]:
        """Normalize diseases."""
        if not diseases:
            return []
        return [
            {
                "id": item.get("id"),
                "common_name": item.get("common_name"),
                "scientific_name": item.get("scientific_name"),
                "description": item.get("description"),
                "solution": item.get("solution"),
                "host": item.get("host"),
            }
            for item in diseases.get("data", [])
        ]
