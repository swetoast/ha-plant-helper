"""Perenual API provider for Plant Helper."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import aiohttp

from .base import ProviderResult, RateLimiter, first_value, normalize_text
from ..const import (
    PERENUAL_ACCESS_FREE,
    PERENUAL_ACCESS_PAID,
    PERENUAL_DAILY_LIMIT,
    PERENUAL_FREE_MAX_SPECIES_ID,
)

_LOGGER = logging.getLogger(__name__)


class PerenualProvider:
    """Perenual plant data provider."""

    def __init__(
        self,
        *,
        session: aiohttp.ClientSession,
        api_key: str | None,
        daily_limit: int = PERENUAL_DAILY_LIMIT,
        access_level: str = PERENUAL_ACCESS_FREE,
    ) -> None:
        """Initialize provider."""
        self.session = session
        self.api_key = api_key or ""
        self.base_url = "https://perenual.com/api"
        self.access_level = (
            access_level if access_level in {PERENUAL_ACCESS_FREE, PERENUAL_ACCESS_PAID}
            else PERENUAL_ACCESS_FREE
        )
        self.limiter = RateLimiter(daily_limit=daily_limit)
        self.last_error: str | None = None
        self.last_success: str | None = None
        self._request_lock = asyncio.Lock()
        self._blocked_until: datetime | None = None

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

        now = datetime.now(timezone.utc)
        if self._blocked_until is not None and now < self._blocked_until:
            self.last_error = "Perenual rate limited; retry later"
            return ProviderResult(False, "perenual", api_checked=True, api_called=False, message=self.last_error)

        if not self.limiter.can_call():
            self.last_error = "Perenual daily limit reached or call interval not ready"
            return ProviderResult(False, "perenual", api_checked=True, api_called=False, message=self.last_error)

        start_calls = self.limiter.calls_today

        def _calls() -> int:
            return self.limiter.calls_today - start_calls

        try:
            payload = await self._get_json(
                f"{self.base_url}/v2/species-list",
                {"key": self.api_key, "q": search_name, "page": 1},
            )
            if payload is None:
                return ProviderResult(False, "perenual", api_checked=True, api_called=bool(_calls()), calls_made=_calls(), message=self.last_error or "Perenual search failed")

            results = payload.get("data") or []
            if not results:
                return ProviderResult(False, "perenual", api_checked=True, api_called=True, calls_made=_calls(), message="Perenual returned no results")

            selected = self._select_best(search_name, results)
            if not selected:
                return ProviderResult(False, "perenual", api_checked=True, api_called=True, calls_made=_calls(), message="No usable Perenual match")

            species_id = selected.get("id")
            detail = selected
            detail_allowed = bool(species_id) and (
                self.access_level == PERENUAL_ACCESS_PAID
                or int(species_id) <= PERENUAL_FREE_MAX_SPECIES_ID
            )
            upgrade_required = False

            if detail_allowed:
                detail_payload = await self._get_json(
                    f"{self.base_url}/v2/species/details/{species_id}",
                    {"key": self.api_key},
                )
                if detail_payload:
                    detail = detail_payload
                elif self.last_error == "Perenual upgrade required":
                    upgrade_required = True
            elif species_id:
                upgrade_required = True

            care_guides = None
            diseases = None
            if detail_allowed and not upgrade_required and species_id and fetch_care_guides:
                care_guides = await self._get_json(
                    f"{self.base_url}/species-care-guide-list",
                    {"key": self.api_key, "species_id": species_id, "page": 1},
                )
            if detail_allowed and not upgrade_required and fetch_diseases:
                diseases = await self._get_json(
                    f"{self.base_url}/pest-disease-list",
                    {"key": self.api_key, "q": search_name, "page": 1},
                )

            data = self._normalize_plant(detail, care_guides=care_guides, diseases=diseases)
            if upgrade_required:
                data["perenual_access"] = "upgrade_required"
            self.last_error = None
            self.last_success = datetime.now().isoformat()

            return ProviderResult(True, "perenual", data=data, api_checked=True, api_called=True, calls_made=_calls(), message=("Perenual search match found; upgrade required for details" if upgrade_required else "Perenual match found"))

        except Exception as err:
            _LOGGER.warning("Perenual lookup failed for %s (%s)", search_name, type(err).__name__)
            self.last_error = f"Perenual request error: {type(err).__name__}"
            return ProviderResult(False, "perenual", api_checked=True, api_called=bool(_calls()), calls_made=_calls(), message="Perenual request failed")

    async def _get_json(self, url: str, params: dict[str, Any]) -> dict[str, Any] | None:
        """GET JSON and track limits without overlapping provider requests."""
        async with self._request_lock:
            if not self.limiter.can_call():
                self.last_error = "Perenual limit reached"
                return None
            self.limiter.mark_call()
            timeout = aiohttp.ClientTimeout(total=10)
            async with self.session.get(url, params=params, timeout=timeout) as response:
                if response.status == 429:
                    text_reader = getattr(response, "text", None)
                    if callable(text_reader):
                        body = (await text_reader()).casefold()
                    else:
                        payload = await response.json(content_type=None)
                        body = str(payload).casefold()
                    if "upgrade" in body:
                        self.last_error = "Perenual upgrade required"
                        return None
                    retry_after = response.headers.get("Retry-After")
                    delay = self._retry_after_seconds(retry_after)
                    self._blocked_until = datetime.now(timezone.utc) + timedelta(seconds=delay)
                    self.last_error = f"Perenual rate limited; retry after {delay} seconds"
                    return None
                if response.status != 200:
                    self.last_error = f"Perenual HTTP {response.status}"
                    return None
                payload = await response.json(content_type=None)
                if not isinstance(payload, dict):
                    self.last_error = "Perenual returned a non-object JSON payload"
                    return None
                return payload
    @staticmethod
    def _retry_after_seconds(value: str | None) -> int:
        """Return a bounded Retry-After delay, defaulting to five minutes."""
        if value:
            try:
                return max(1, min(86400, int(value)))
            except (TypeError, ValueError):
                try:
                    retry_at = parsedate_to_datetime(value)
                    if retry_at.tzinfo is None:
                        retry_at = retry_at.replace(tzinfo=timezone.utc)
                    seconds = int((retry_at - datetime.now(timezone.utc)).total_seconds())
                    return max(1, min(86400, seconds))
                except (TypeError, ValueError, OverflowError):
                    pass
        return 300

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
        """Normalize populated Perenual fields without restricted placeholders."""
        scientific_name = first_value(data.get("scientific_name"))
        species = scientific_name or data.get("species") or data.get("common_name")
        common_name = data.get("common_name") or species
        hardiness = data.get("hardiness") or {}
        normalized = {
            "species": species,
            "common_name": common_name,
            "scientific_name": scientific_name,
            "other_name": data.get("other_name"),
            "family": data.get("family"),
            "hybrid": data.get("hybrid"),
            "authority": data.get("authority"),
            "subspecies": data.get("subspecies"),
            "cultivar": data.get("cultivar"),
            "variety": data.get("variety"),
            "species_epithet": data.get("species_epithet"),
            "genus": data.get("genus"),
            "origin": data.get("origin"),
            "plant_type": data.get("type"),
            "dimensions": data.get("dimensions"),
            "cycle": data.get("cycle"),
            "attracts": data.get("attracts"),
            "propagation": data.get("propagation"),
            "hardiness_min": hardiness.get("min"),
            "hardiness_max": hardiness.get("max"),
            "watering": data.get("watering"),
            "watering_general_benchmark": data.get("watering_general_benchmark"),
            "plant_anatomy": data.get("plant_anatomy"),
            "sunlight": data.get("sunlight"),
            "pruning_month": data.get("pruning_month"),
            "pruning_count": data.get("pruning_count"),
            "seeds": data.get("seeds"),
            "maintenance": data.get("maintenance"),
            "soil": data.get("soil"),
            "growth_rate": data.get("growth_rate"),
            "drought_tolerant": data.get("drought_tolerant"),
            "salt_tolerant": data.get("salt_tolerant"),
            "thorny": data.get("thorny"),
            "invasive": data.get("invasive"),
            "tropical": data.get("tropical"),
            "indoor": data.get("indoor"),
            "care_level": data.get("care_level"),
            "pest_susceptibility": data.get("pest_susceptibility"),
            "flowers": data.get("flowers"),
            "flowering_season": data.get("flowering_season"),
            "cones": data.get("cones"),
            "fruits": data.get("fruits"),
            "edible_fruit": data.get("edible_fruit"),
            "harvest_season": data.get("harvest_season"),
            "leaf": data.get("leaf"),
            "edible_leaf": data.get("edible_leaf"),
            "cuisine": data.get("cuisine"),
            "medicinal": data.get("medicinal"),
            "poisonous_to_humans": data.get("poisonous_to_humans"),
            "poisonous_to_pets": data.get("poisonous_to_pets"),
            "description": data.get("description"),
            "default_image": data.get("default_image"),
            "other_images": data.get("other_images"),
            "thresholds": self._thresholds(data),
            "tips": self._tips(data, care_guides),
            "facts": self._facts(data),
            "common_diseases": self._diseases(diseases),
            "source": "perenual",
            "provider": "perenual",
            "provider_id": data.get("id"),
            "updated_at": datetime.now().isoformat(),
        }
        return self._without_empty(normalized)

    @classmethod
    def _without_empty(cls, value: Any) -> Any:
        """Remove null, empty, upgrade-only, and credential-bearing values."""
        if isinstance(value, dict):
            cleaned = {key: cls._without_empty(item) for key, item in value.items()}
            return {key: item for key, item in cleaned.items() if item not in (None, "", [], {})}
        if isinstance(value, list):
            cleaned = [cls._without_empty(item) for item in value]
            return [item for item in cleaned if item not in (None, "", [], {})]
        if isinstance(value, str):
            text = value.strip()
            folded = text.casefold()
            if not text or folded in {"null", "none"} or "upgrade plan" in folded or "upgrade_access.jpg" in folded:
                return None
            if "key=" in folded or "<iframe" in folded:
                return None
            return text
        return value

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
