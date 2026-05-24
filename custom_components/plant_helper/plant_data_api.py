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

    @property
    def _api_calls_today(self) -> int:
        """Compatibility property for binary sensor."""
        return self.perenual.limiter.calls_today

    @property
    def _last_reset(self):
        """Compatibility property for binary sensor."""
        return self.perenual.limiter.last_reset

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
        """Fetch plant through provider chain."""
        search_name = search_name.strip()
        if not search_name:
            self._last_error = "Empty plant search"
            return ProviderResult(False, "none", message=self._last_error)

        if not force_fetch and self.storage:
            cached = self.storage.get_plant_by_name(search_name)
            if cached:
                self._last_error = None
                self._last_success = datetime.now().isoformat()
                self._last_provider = "local_cache"
                return ProviderResult(
                    True,
                    "local_cache",
                    data=cached,
                    api_checked=False,
                    api_called=False,
                    message="Local database cache hit",
                )

        perenual_result = await self.perenual.fetch(
            search_name,
            fetch_care_guides=fetch_care_guides,
            fetch_diseases=fetch_diseases,
        )
        if perenual_result.found and perenual_result.data:
            data = await self._enrich(perenual_result.data)
            self._record_success("perenual")
            return ProviderResult(
                True,
                "perenual",
                data=data,
                api_checked=True,
                api_called=True,
                calls_made=perenual_result.calls_made,
                message="Perenual primary provider matched plant",
                metadata={"perenual": perenual_result.metadata},
            )

        trefle_result = await self.trefle.fetch(search_name)
        if trefle_result.found and trefle_result.data:
            data = await self._enrich(trefle_result.data)
            self._record_success("trefle")
            return ProviderResult(
                True,
                "trefle",
                data=data,
                api_checked=True,
                api_called=True,
                calls_made=perenual_result.calls_made + trefle_result.calls_made,
                message="Perenual miss, Trefle fallback matched plant",
                metadata={
                    "perenual_message": perenual_result.message,
                    "trefle_message": trefle_result.message,
                },
            )

        self._last_error = f"No plant found. Perenual: {perenual_result.message}; Trefle: {trefle_result.message}"
        return ProviderResult(
            False,
            "none",
            api_checked=True,
            api_called=perenual_result.api_called or trefle_result.api_called,
            calls_made=perenual_result.calls_made + trefle_result.calls_made,
            message=self._last_error,
            metadata={
                "perenual_message": perenual_result.message,
                "trefle_message": trefle_result.message,
            },
        )

    async def _enrich(self, plant_data: dict[str, Any]) -> dict[str, Any]:
        """Apply optional enrichment providers."""
        if not self.enable_inaturalist_enrichment:
            return plant_data

        enrichment = await self.inaturalist.enrich(plant_data)
        if enrichment.data:
            plant_data["inat"] = enrichment.data
            plant_data["inaturalist_enriched"] = enrichment.found
            plant_data["inaturalist_message"] = enrichment.message
        return plant_data

    def _record_success(self, provider: str) -> None:
        """Record successful provider."""
        self._last_error = None
        self._last_success = datetime.now().isoformat()
        self._last_provider = provider
