"""Trefle botanical context provider for Plant Helper."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

import aiohttp

from .base import ProviderResult, RateLimiter, normalize_text
from ..const import TREFLE_DAILY_LIMIT

_LOGGER = logging.getLogger(__name__)


class TrefleProvider:
    """Trefle identity, taxonomy, distribution, and image provider."""

    def __init__(
        self,
        *,
        session: aiohttp.ClientSession,
        api_key: str | None,
        enabled: bool = True,
        daily_limit: int = TREFLE_DAILY_LIMIT,
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
        self._request_lock = asyncio.Lock()

    async def fetch(self, search_name: str) -> ProviderResult:
        """Fetch plant from Trefle."""
        if not self.enabled:
            return ProviderResult(False, "trefle", api_checked=False, api_called=False, message="Trefle provider disabled")
        if not self.api_key:
            return ProviderResult(False, "trefle", api_checked=False, api_called=False, message="Trefle token missing")
        if not self.limiter.has_daily_capacity():
            return ProviderResult(False, "trefle", api_checked=True, api_called=False, message="Trefle limit reached or interval not ready")

        start_calls = self.limiter.calls_today

        def _calls() -> int:
            return self.limiter.calls_today - start_calls

        try:
            payload = await self._get_json(f"{self.base_url}/species/search", {"token": self.api_key, "q": search_name, "page": 1})
            if payload is None:
                return ProviderResult(False, "trefle", api_checked=True, api_called=bool(_calls()), calls_made=_calls(), message=self.last_error or "Trefle search failed")

            results = payload.get("data") or []
            if not results:
                return ProviderResult(False, "trefle", api_checked=True, api_called=True, calls_made=_calls(), message="Trefle returned no results")

            selected = self._select_best(search_name, results)
            if not selected:
                return ProviderResult(False, "trefle", api_checked=True, api_called=True, calls_made=_calls(), message="No usable Trefle match")

            detail_data = selected
            links = selected.get("links") or {}
            plant_link = links.get("plant")
            self_link = links.get("self")
            slug = selected.get("slug")

            detail_payload = None
            if plant_link:
                detail_payload = await self._get_path(plant_link)
            if not detail_payload and self_link:
                detail_payload = await self._get_path(self_link)
            if not detail_payload and slug:
                detail_payload = await self._get_path(f"/api/v1/species/{slug}")

            if detail_payload and isinstance(detail_payload.get("data"), dict):
                detail_data = {
                    **selected,
                    **detail_payload["data"],
                    "_response_meta": detail_payload.get("meta") or {},
                }

            data = self._normalize(detail_data)
            self.last_error = None
            self.last_success = datetime.now().isoformat()
            return ProviderResult(True, "trefle", data=data, api_checked=True, api_called=True, calls_made=_calls(), message="Trefle match found")

        except Exception as err:
            _LOGGER.warning("Trefle lookup failed for %s (%s)", search_name, type(err).__name__)
            self.last_error = f"Trefle request error: {type(err).__name__}"
            return ProviderResult(False, "trefle", api_checked=True, api_called=bool(_calls()), calls_made=_calls(), message="Trefle request failed")

    async def _get_json(self, url: str, params: dict[str, Any]) -> dict[str, Any] | None:
        """GET JSON from Trefle without overlapping provider requests."""
        async with self._request_lock:
            if not await self.limiter.async_wait_for_slot():
                self.last_error = "Trefle daily limit reached"
                return None
            self.limiter.mark_call()
            timeout = aiohttp.ClientTimeout(total=10)
            async with self.session.get(url, params=params, timeout=timeout) as response:
                if response.status != 200:
                    self.last_error = f"Trefle HTTP {response.status}"
                    return None
                payload = await response.json(content_type=None)
                if not isinstance(payload, dict):
                    self.last_error = "Trefle returned a non-object JSON payload"
                    return None
                return payload
    async def _get_path(self, path: str) -> dict[str, Any] | None:
        """GET a path returned by Trefle links."""
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

    @staticmethod
    def _without_empty(value: Any) -> Any:
        """Recursively omit null and empty values while preserving False and zero."""
        if isinstance(value, dict):
            cleaned = {
                key: TrefleProvider._without_empty(item)
                for key, item in value.items()
            }
            return {
                key: item
                for key, item in cleaned.items()
                if item is not None and item != "" and item != [] and item != {}
            }
        if isinstance(value, list):
            cleaned = [TrefleProvider._without_empty(item) for item in value]
            return [
                item
                for item in cleaned
                if item is not None and item != "" and item != [] and item != {}
            ]
        if isinstance(value, str):
            stripped = value.strip()
            return stripped if stripped and stripped.casefold() not in {"null", "none"} else None
        return value

    @staticmethod
    def _synonym_names(value: Any) -> list[str]:
        """Normalize Trefle search and detail synonym shapes to names."""
        names: list[str] = []
        for item in value or []:
            name = item.get("name") if isinstance(item, dict) else item
            if isinstance(name, str) and name.strip():
                names.append(name.strip())
        return list(dict.fromkeys(names))

    @staticmethod
    def _image_context(images: Any) -> dict[str, list[dict[str, Any]]]:
        """Keep a compact licensed image sample from each populated category."""
        if not isinstance(images, dict):
            return {}
        result: dict[str, list[dict[str, Any]]] = {}
        for category, entries in images.items():
            kept: list[dict[str, Any]] = []
            for item in entries or []:
                if not isinstance(item, dict) or not item.get("image_url"):
                    continue
                kept.append({
                    key: item.get(key)
                    for key in ("image_url", "copyright")
                    if item.get(key) not in (None, "")
                })
                if len(kept) >= 2:
                    break
            if kept:
                result[category] = kept
        return result

    def _normalize(self, data: dict[str, Any]) -> dict[str, Any]:
        """Normalize useful free Trefle identity and botanical context only."""
        main = data.get("main_species") or {}
        scientific_name = data.get("scientific_name") or main.get("scientific_name")
        common_name = data.get("common_name") or scientific_name or data.get("slug")
        response_meta = data.get("_response_meta") or {}
        distribution = data.get("distribution") or {}
        specifications = data.get("specifications") or {}
        flower = data.get("flower") or {}
        foliage = data.get("foliage") or {}

        sources = []
        for source in data.get("sources") or []:
            if not isinstance(source, dict):
                continue
            sources.append({
                key: source.get(key)
                for key in ("name", "url", "citation", "licence", "licence_url")
                if source.get(key) not in (None, "")
            })

        normalized = {
            "species": scientific_name or data.get("slug") or common_name,
            "common_name": common_name,
            "scientific_name": scientific_name,
            "common_names": data.get("common_names"),
            "other_name": self._flatten_common_names(data.get("common_names") or {}),
            "family": data.get("family"),
            "family_common_name": data.get("family_common_name"),
            "genus": data.get("genus"),
            "rank": data.get("rank"),
            "status": data.get("status"),
            "slug": data.get("slug"),
            "author": data.get("author"),
            "year": data.get("year"),
            "bibliography": data.get("bibliography"),
            "observations": data.get("observations"),
            "native_distribution": distribution.get("native"),
            "introduced_distribution": distribution.get("introduced"),
            "growth_habit": specifications.get("growth_habit"),
            "flower_color": flower.get("color"),
            "foliage_color": foliage.get("color"),
            "edible": data.get("edible"),
            "vegetable": data.get("vegetable"),
            "image_url": data.get("image_url"),
            "images": self._image_context(data.get("images")),
            "synonyms": self._synonym_names(data.get("synonyms")),
            "sources": sources,
            "completion_ratio": data.get("completion_ratio"),
            "complete_data": data.get("complete_data"),
            "images_count": response_meta.get("images_count"),
            "sources_count": response_meta.get("sources_count"),
            "synonyms_count": response_meta.get("synonyms_count"),
            "provider_last_modified": response_meta.get("last_modified"),
            "growth": self._without_empty(data.get("growth") or {}),
            "source": "trefle",
            "provider": "trefle",
            "provider_id": data.get("id"),
            "updated_at": datetime.now().isoformat(),
        }
        return self._without_empty(normalized)

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
