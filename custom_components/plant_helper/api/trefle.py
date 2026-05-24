"""Trefle API fallback provider for Plant Helper."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import aiohttp

from .base import ProviderResult, RateLimiter, normalize_text

_LOGGER = logging.getLogger(__name__)


class TrefleProvider:
    """Trefle fallback provider."""

    def __init__(
        self,
        *,
        session: aiohttp.ClientSession,
        api_key: str | None,
        enabled: bool = True,
        daily_limit: int = 500,
        min_interval_seconds: int = 2,
    ) -> None:
        """Initialize provider."""
        self.session = session
        self.api_key = api_key or ""
        self.enabled = enabled
        self.base_url = "https://trefle.io/api/v1"
        self.limiter = RateLimiter(daily_limit=daily_limit, min_interval_seconds=min_interval_seconds)
        self.last_error: str | None = None
        self.last_success: str | None = None

    async def fetch(self, search_name: str) -> ProviderResult:
        """Fetch plant from Trefle."""
        if not self.enabled:
            return ProviderResult(False, "trefle", api_checked=False, api_called=False, message="Trefle fallback disabled")
        if not self.api_key:
            return ProviderResult(False, "trefle", api_checked=False, api_called=False, message="Trefle token missing")
        if not self.limiter.can_call():
            return ProviderResult(False, "trefle", api_checked=True, api_called=False, message="Trefle limit reached or interval not ready")

        try:
            payload = await self._get_json(f"{self.base_url}/plants/search", {"token": self.api_key, "q": search_name, "page": 1})
            if payload is None:
                return ProviderResult(False, "trefle", api_checked=True, api_called=True, calls_made=1, message=self.last_error or "Trefle search failed")

            results = payload.get("data") or []
            if not results:
                return ProviderResult(False, "trefle", api_checked=True, api_called=True, calls_made=1, message="Trefle returned no results")

            selected = self._select_best(search_name, results)
            if not selected:
                return ProviderResult(False, "trefle", api_checked=True, api_called=True, calls_made=1, message="No usable Trefle match")

            calls = 1
            detail_data = selected
            links = selected.get("links") or {}
            plant_link = links.get("plant")
            self_link = links.get("self")
            slug = selected.get("slug")

            detail_payload = None
            if plant_link:
                detail_payload = await self._get_path(plant_link)
                calls += 1
            if not detail_payload and self_link:
                detail_payload = await self._get_path(self_link)
                calls += 1
            if not detail_payload and slug:
                detail_payload = await self._get_path(f"/api/v1/plants/{slug}")
                calls += 1

            if detail_payload and isinstance(detail_payload.get("data"), dict):
                detail_data = {**selected, **detail_payload["data"]}

            data = self._normalize(detail_data)
            self.last_error = None
            self.last_success = datetime.now().isoformat()
            return ProviderResult(True, "trefle", data=data, api_checked=True, api_called=True, calls_made=calls, message="Trefle match found")

        except Exception as err:
            _LOGGER.exception("Trefle lookup failed for %s", search_name)
            self.last_error = str(err)
            return ProviderResult(False, "trefle", api_checked=True, api_called=True, message=f"Trefle error: {err}")

    async def _get_json(self, url: str, params: dict[str, Any]) -> dict[str, Any] | None:
        """GET JSON from Trefle."""
        if not self.limiter.can_call():
            self.last_error = "Trefle limit reached"
            return None
        self.limiter.mark_call()
        async with self.session.get(url, params=params, timeout=10) as response:
            if response.status == 401:
                self.last_error = "Trefle invalid token"
                return None
            if response.status != 200:
                text = await response.text()
                self.last_error = f"Trefle HTTP {response.status}: {text[:200]}"
                return None
            return await response.json()

    async def _get_path(self, path: str) -> dict[str, Any] | None:
        """GET Trefle path returned by links."""
        url = path if path.startswith("http") else f"https://trefle.io{path}"
        return await self._get_json(url, {"token": self.api_key})

    def _select_best(self, search_name: str, results: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Select best Trefle result."""
        search = normalize_text(search_name)
        candidates = [r for r in results if r.get("status") in (None, "accepted") and r.get("rank") in (None, "species")] or results
        for item in candidates:
            if normalize_text(item.get("common_name")) == search:
                return item
            if normalize_text(item.get("scientific_name")) == search:
                return item
            for synonym in item.get("synonyms") or []:
                if normalize_text(synonym) == search:
                    return item
        for item in candidates:
            common = normalize_text(item.get("common_name"))
            if common and search in common:
                return item
        return candidates[0] if candidates else None

    def _normalize(self, data: dict[str, Any]) -> dict[str, Any]:
        """Normalize Trefle data to Plant Helper format."""
        scientific_name = data.get("scientific_name")
        common_name = data.get("common_name") or scientific_name or data.get("slug")
        species = scientific_name or data.get("slug") or common_name
        growth = data.get("growth") or {}
        specifications = data.get("specifications") or {}
        images = data.get("images") or {}

        return {
            "species": species,
            "common_name": common_name,
            "scientific_name": scientific_name,
            "other_name": self._flatten_common_names(data.get("common_names") or {}),
            "family": data.get("family"),
            "family_common_name": data.get("family_common_name"),
            "genus": data.get("genus"),
            "rank": data.get("rank"),
            "status": data.get("status"),
            "slug": data.get("slug"),
            "image_url": data.get("image_url"),
            "default_image": self._default_image(data),
            "images": images,
            "synonyms": data.get("synonyms", []),
            "duration": data.get("duration"),
            "edible": data.get("edible"),
            "edible_part": data.get("edible_part"),
            "vegetable": data.get("vegetable"),
            "observations": data.get("observations"),
            "distribution": data.get("distribution"),
            "distributions": data.get("distributions"),
            "foliage": data.get("foliage"),
            "flower": data.get("flower"),
            "fruit_or_seed": data.get("fruit_or_seed"),
            "specifications": specifications,
            "growth": growth,
            "thresholds": self._thresholds(data),
            "tips": self._tips(data),
            "facts": self._facts(data),
            "source": "trefle",
            "provider": "trefle",
            "provider_id": data.get("id"),
            "updated_at": datetime.now().isoformat(),
        }

    def _thresholds(self, data: dict[str, Any]) -> dict[str, Any]:
        """Build thresholds from Trefle growth fields."""
        growth = data.get("growth") or {}
        thresholds: dict[str, Any] = {}
        light = growth.get("light")
        air = growth.get("atmospheric_humidity")
        soil = growth.get("soil_humidity") or growth.get("ground_humidity")
        min_temp = self._nested(growth, "minimum_temperature", "deg_c")
        max_temp = self._nested(growth, "maximum_temperature", "deg_c")
        if isinstance(light, (int, float)):
            thresholds["lux_min"] = self._light_to_lux(light)
            thresholds["trefle_light_scale"] = light
        if isinstance(air, (int, float)):
            thresholds["air_humidity_min"] = max(0, int(air * 10) - 10)
            thresholds["air_humidity_max"] = min(100, int(air * 10) + 20)
            thresholds["trefle_atmospheric_humidity_scale"] = air
        if isinstance(soil, (int, float)):
            thresholds["soil_moisture_min"] = max(0, int(soil * 10) - 15)
            thresholds["soil_moisture_max"] = min(100, int(soil * 10) + 20)
            thresholds["trefle_soil_humidity_scale"] = soil
        if min_temp is not None:
            thresholds["temperature_min"] = min_temp
        if max_temp is not None:
            thresholds["temperature_max"] = max_temp
        if growth.get("ph_minimum") is not None:
            thresholds["ph_min"] = growth.get("ph_minimum")
        if growth.get("ph_maximum") is not None:
            thresholds["ph_max"] = growth.get("ph_maximum")
        return thresholds

    def _tips(self, data: dict[str, Any]) -> dict[str, list[str]]:
        """Build tips."""
        growth = data.get("growth") or {}
        direct: list[str] = []
        seasonal: list[str] = []
        if growth.get("description"):
            direct.append(growth["description"])
        if growth.get("sowing"):
            direct.append(f"Sowing: {growth['sowing']}")
        if growth.get("light") is not None:
            direct.append(f"Trefle light requirement scale: {growth['light']}/10")
        if growth.get("atmospheric_humidity") is not None:
            direct.append(f"Trefle atmospheric humidity requirement scale: {growth['atmospheric_humidity']}/10")
        if growth.get("soil_humidity") is not None:
            direct.append(f"Trefle soil humidity requirement scale: {growth['soil_humidity']}/10")
        if growth.get("bloom_months"):
            seasonal.append("Bloom months: " + ", ".join(growth["bloom_months"]))
        if growth.get("growth_months"):
            seasonal.append("Growth months: " + ", ".join(growth["growth_months"]))
        return {"direct": list(dict.fromkeys(direct)), "seasonal": list(dict.fromkeys(seasonal))}

    def _facts(self, data: dict[str, Any]) -> list[str]:
        """Build facts."""
        facts: list[str] = []
        for key, label in (("family", "Family"), ("family_common_name", "Family common name"), ("genus", "Genus"), ("rank", "Rank"), ("status", "Taxonomic status"), ("observations", "Observations")):
            if data.get(key):
                facts.append(f"{label}: {data[key]}")
        specs = data.get("specifications") or {}
        if specs.get("toxicity"):
            facts.append(f"Toxicity: {specs['toxicity']}")
        if specs.get("growth_rate"):
            facts.append(f"Growth rate: {specs['growth_rate']}")
        return facts

    def _default_image(self, data: dict[str, Any]) -> dict[str, Any] | None:
        """Build default image object."""
        if data.get("image_url"):
            url = data["image_url"]
            return {"original_url": url, "regular_url": url, "medium_url": url, "small_url": url, "thumbnail": url, "source": "trefle"}
        images = data.get("images") or {}
        for category in ("habit", "leaf", "flower", "fruit", "bark", "other"):
            values = images.get(category) or []
            if values and values[0].get("image_url"):
                url = values[0]["image_url"]
                return {"original_url": url, "regular_url": url, "medium_url": url, "small_url": url, "thumbnail": url, "copyright": values[0].get("copyright"), "category": category, "source": "trefle"}
        return None

    def _flatten_common_names(self, common_names: dict[str, Any]) -> list[str]:
        """Flatten Trefle common names."""
        names: list[str] = []
        if isinstance(common_names, dict):
            for values in common_names.values():
                if isinstance(values, list):
                    names.extend([v.strip() for v in values if isinstance(v, str) and v.strip()])
        return list(dict.fromkeys(names))

    def _light_to_lux(self, light: int | float) -> int:
        """Map 0-10 Trefle light scale to rough lux min."""
        if light <= 1:
            return 10
        if light <= 3:
            return 500
        if light <= 5:
            return 1500
        if light <= 7:
            return 5000
        if light <= 9:
            return 10000
        return 20000

    def _nested(self, data: dict[str, Any], key: str, subkey: str) -> Any:
        """Read nested dict value."""
        value = data.get(key)
        return value.get(subkey) if isinstance(value, dict) else None
