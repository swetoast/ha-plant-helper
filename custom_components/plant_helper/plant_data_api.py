"""Plant data API orchestrator for Plant Helper."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import aiohttp

from .api import INaturalistProvider, PerenualProvider, ProviderResult, TrefleProvider

_LOGGER = logging.getLogger(__name__)


class PlantDataAPI:
    """Orchestrate plant provider lookups.

    Order:
    1. Local cache
    2. Perenual primary
    3. Trefle fallback
    4. iNaturalist enrichment after a plant is found
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        perenual_key: str | None = None,
        storage: Any = None,
        trefle_key: str | None = None,
        enable_trefle_fallback: bool = True,
        enable_inaturalist_enrichment: bool = True,
    ) -> None:
        """Initialize orchestrator."""
        self.session = session
        self.perenual_key = perenual_key or ""
        self.trefle_key = trefle_key or ""
        self.storage = storage
        self.enable_trefle_fallback = enable_trefle_fallback
        self.enable_inaturalist_enrichment = enable_inaturalist_enrichment

        self.perenual = PerenualProvider(session=session, api_key=self.perenual_key)
        self.trefle = TrefleProvider(session=session, api_key=self.trefle_key, enabled=enable_trefle_fallback)
        self.inaturalist = INaturalistProvider(session=session, enabled=enable_inaturalist_enrichment)

        self._last_error: str | None = None
        self._last_success: str | None = None
        self._last_provider: str | None = None
        self._base_url = self.perenual.base_url

    def provider_status(self) -> dict[str, Any]:
        """Per-provider health/diagnostics for the API binary sensors."""
        def _rl(limiter) -> dict[str, Any]:
            limit = getattr(limiter, "daily_limit", None)
            used = getattr(limiter, "calls_today", 0)
            rate_limited = limit is not None and used >= limit
            return {"calls_today": used, "daily_limit": limit, "rate_limited": rate_limited}

        return {
            "perenual": {
                "enabled": bool(self.perenual.api_key),
                "has_key": bool(self.perenual.api_key),
                **_rl(self.perenual.limiter),
            },
            "trefle": {
                "enabled": bool(self.trefle.enabled and self.trefle.api_key),
                "has_key": bool(self.trefle.api_key),
                **_rl(self.trefle.limiter),
            },
            "inaturalist": {
                "enabled": bool(self.inaturalist.enabled),
                "has_key": False,
                "rate_limited": False,
            },
            "last_provider": self._last_provider,
            "last_error": self._last_error,
            "last_success": self._last_success,
        }

    async def fetch_perenual_plant(
        self,
        species_name: str,
        force_fetch: bool = False,
        fetch_care_guides: bool = True,
        fetch_diseases: bool = True,
    ) -> dict[str, Any] | None:
        """Compatibility method used by existing config/services.

        Despite the historical method name, this now uses the provider chain:
        local cache -> Perenual -> Trefle fallback -> iNaturalist enrichment.
        """
        result = await self.fetch_plant(
            species_name,
            force_fetch=force_fetch,
            fetch_care_guides=fetch_care_guides,
            fetch_diseases=fetch_diseases,
        )
        return result.data if result.found else None

    async def fetch_plant(
        self,
        search_name: str,
        *,
        force_fetch: bool = False,
        fetch_care_guides: bool = True,
        fetch_diseases: bool = True,
    ) -> ProviderResult:
        """Resolve and merge species data across all three providers.

        Perenual (care) + iNaturalist (identity/photo, keyless) + Trefle
        (botanical). iNaturalist is a first-class resolver, not just a photo add-
        on, so adding a plant returns useful data even with no API keys. The
        merged record is cached under the resolved scientific name.
        """
        from .enrichment import merge_provider_data

        search_name = (search_name or "").strip()
        if not search_name:
            self._last_error = "Empty plant search"
            return ProviderResult(False, "none", message=self._last_error)

        if not force_fetch and self.storage:
            cached = self.storage.get_plant_by_name(search_name)
            if cached:
                self._record_success("local_cache")
                return ProviderResult(
                    True, "local_cache", data=cached,
                    api_checked=False, api_called=False, message="Local database cache hit",
                )

        parts: list[dict[str, Any]] = []
        calls = 0
        messages: dict[str, str] = {}

        # 1. iNaturalist FIRST (keyless) — resolve the canonical scientific name
        #    and identity/photo. Everything else is looked up by that name.
        inat_result = await self.inaturalist.resolve(search_name)
        calls += inat_result.calls_made
        messages["inaturalist"] = inat_result.message
        if inat_result.found and inat_result.data:
            parts.append(inat_result.data)

        scientific = None
        for part in parts:
            if part.get("scientific_name"):
                scientific = part["scientific_name"]
                break
        lookup_term = scientific or search_name

        # 2. Perenual — care data, looked up BY SCIENTIFIC NAME (its search needs
        #    the botanical name to match correctly).
        perenual_result = await self.perenual.fetch(
            lookup_term, fetch_care_guides=fetch_care_guides, fetch_diseases=fetch_diseases
        )
        calls += perenual_result.calls_made
        messages["perenual"] = perenual_result.message
        if perenual_result.found and perenual_result.data:
            parts.append({**perenual_result.data, "provider": "perenual"})

        # 3. Trefle — botanical priors, also by scientific name (search -> detail).
        trefle_result = await self.trefle.fetch(lookup_term)
        calls += trefle_result.calls_made
        messages["trefle"] = trefle_result.message
        if trefle_result.found and trefle_result.data:
            parts.append({**trefle_result.data, "provider": "trefle"})

        if not parts:
            self._last_error = (
                f"No plant found for '{search_name}'. "
                f"Perenual: {messages['perenual']}; iNaturalist: {messages['inaturalist']}; "
                f"Trefle: {messages['trefle']}"
            )
            return ProviderResult(
                False, "none", api_checked=True, api_called=True, calls_made=calls,
                message=self._last_error, metadata=messages,
            )

        merged = merge_provider_data(parts)
        used = merged.get("providers", [])
        if self.storage:
            # Cache under the search term (the plant's species field) so later
            # lookups by that term hit the rich data, and also under the resolved
            # scientific name for cross-reference.
            await self.storage.async_add_plant(search_name, merged)
            sci = merged.get("scientific_name")
            if sci and sci != search_name and self.storage.get_plant(sci) is None:
                await self.storage.async_add_plant(sci, merged)
        self._record_success("+".join(used) or "none")
        return ProviderResult(
            True, "+".join(used) or "none", data=merged,
            api_checked=True, api_called=True, calls_made=calls,
            message=f"Merged providers: {', '.join(used)}", metadata=messages,
        )

    async def _enrich(self, plant_data: dict[str, Any]) -> dict[str, Any]:
        """Apply optional enrichment providers."""
        if not self.enable_inaturalist_enrichment:
            # Add debug info even when disabled
            plant_data["inaturalist_enriched"] = False
            plant_data["inaturalist_message"] = "iNaturalist enrichment disabled in config"
            return plant_data

        enrichment = await self.inaturalist.enrich(plant_data)
        
        # Always add enrichment status for debugging
        plant_data["inaturalist_enriched"] = enrichment.found
        plant_data["inaturalist_message"] = enrichment.message
        
        if enrichment.data:
            plant_data["inat"] = enrichment.data
        else:
            # Add empty structure with error info for visibility
            plant_data["inat"] = {
                "provider": "inaturalist",
                "photos": [],
                "observation_count": 0,
                "error": enrichment.message,
            }
        
        return plant_data

    def _record_success(self, provider: str) -> None:
        """Record successful provider."""
        self._last_error = None
        self._last_success = datetime.now().isoformat()
        self._last_provider = provider
