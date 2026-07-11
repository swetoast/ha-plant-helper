"""iNaturalist enrichment provider for Plant Helper."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

import aiohttp

from .base import ProviderResult, RateLimiter
from ..const import INATURALIST_DAILY_LIMIT

_LOGGER = logging.getLogger(__name__)


class INaturalistProvider:
    """Optional iNaturalist observations/photo enrichment."""

    def __init__(
        self,
        *,
        session: aiohttp.ClientSession,
        enabled: bool = True,
        daily_limit: int = INATURALIST_DAILY_LIMIT,
        min_interval_seconds: int = 3,
    ) -> None:
        """Initialize provider."""
        self.session = session
        self.enabled = enabled
        self.base_url = "https://api.inaturalist.org/v1"
        self.limiter = RateLimiter(daily_limit=daily_limit, min_interval_seconds=min_interval_seconds)
        self.last_error: str | None = None
        self.last_success: str | None = None

    async def resolve(self, query: str) -> ProviderResult:
        """Resolve a plant's identity via the taxa endpoint (keyless).

        Returns scientific name, preferred common name, a photo, and the
        Wikipedia summary — the identity backbone that works with no API key, so
        adding a plant always gets *some* data even without Perenual/Trefle.
        """
        if not self.enabled:
            return ProviderResult(False, "inaturalist", message="iNaturalist disabled")
        cleaned = self._clean_query(query or "")
        if not cleaned:
            return ProviderResult(False, "inaturalist", message="No query for iNaturalist")
        try:
            params: dict[str, Any] = {
                "q": cleaned,
                "is_active": "true",
                "per_page": 10,
                "locale": "en",
            }
            payload = await self._get_json(f"{self.base_url}/taxa/autocomplete", params)
            if payload is None:
                return ProviderResult(False, "inaturalist", api_checked=True, api_called=True, calls_made=1, message=self.last_error or "iNaturalist autocomplete failed")
            results = payload.get("results") or []
            # Prefer the best-ranked plant taxon (autocomplete mixes kingdoms).
            taxon = None
            for cand in results:
                if cand.get("iconic_taxon_name") == "Plantae":
                    taxon = cand
                    break
            if taxon is None and results:
                taxon = results[0]
            if taxon is None:
                return ProviderResult(False, "inaturalist", api_checked=True, api_called=True, calls_made=1, message="No iNaturalist match")
            default_photo = taxon.get("default_photo") or {}
            photo = (
                default_photo.get("medium_url")
                or default_photo.get("url")
                or default_photo.get("square_url")
            )
            # iNaturalist size qualifier: prefer a real display size over 'square'.
            if isinstance(photo, str):
                photo = photo.replace("/square.", "/medium.")
            taxon_id = taxon.get("id")
            # Sparse taxa can lack a default photo; fall back to the best-voted
            # observation photo (this is how v3 reliably got images).
            if not photo and taxon_id:
                photo = await self._observation_photo(taxon_id)
            summary = taxon.get("wikipedia_summary")
            if isinstance(summary, str):
                summary = re.sub(r"<[^>]+>", "", summary).strip() or None
            family = None
            for anc in taxon.get("ancestors") or []:
                if anc.get("rank") == "family":
                    family = anc.get("name")
                    break
            data = {
                "provider": "inaturalist",
                "scientific_name": taxon.get("name"),
                "common_name": taxon.get("preferred_common_name"),
                "family": family,
                "description": summary,
                "wikipedia_url": taxon.get("wikipedia_url"),
                "photo": photo,
                "photos": [photo] if photo else [],
                "taxon_id": taxon_id,
                "observations_count": taxon.get("observations_count"),
            }
            self.last_error = None
            self.last_success = datetime.now().isoformat()
            return ProviderResult(True, "inaturalist", data=data, api_checked=True, api_called=True, calls_made=1, message=f"Resolved to {taxon.get('name')}")
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("iNaturalist taxa resolve failed for %s", query)
            self.last_error = str(err)
            return ProviderResult(False, "inaturalist", api_checked=True, api_called=True, message=f"iNaturalist error: {err}")

    async def _observation_photo(self, taxon_id: Any) -> str | None:
        """Best-voted observation photo for a taxon (fallback when the taxon has
        no default photo). Returns a medium-size URL or None."""
        try:
            params = {
                "taxon_id": taxon_id,
                "photos": "true",
                "per_page": 1,
                "order_by": "votes",
                "quality_grade": "research",
            }
            payload = await self._get_json(f"{self.base_url}/observations", params)
            if not payload:
                return None
            for obs in payload.get("results") or []:
                for photo in obs.get("photos") or []:
                    url = (
                        photo.get("large_url") or photo.get("medium_url")
                        or photo.get("url")
                    )
                    if isinstance(url, str) and url.startswith("http"):
                        return url.replace("/square.", "/medium.")
            return None
        except Exception:  # noqa: BLE001 - photo is optional
            return None

    async def enrich(self, plant_data: dict[str, Any]) -> ProviderResult:
        """Enrich an already identified plant with iNaturalist observations."""
        if not self.enabled:
            return ProviderResult(False, "inaturalist", api_checked=False, api_called=False, message="iNaturalist enrichment disabled")
        if not self.limiter.can_call():
            return ProviderResult(False, "inaturalist", api_checked=True, api_called=False, message="iNaturalist limit reached or interval not ready")

        # Get query and clean it for iNaturalist
        raw_query = plant_data.get("scientific_name") or plant_data.get("common_name") or plant_data.get("species")
        if not raw_query:
            return ProviderResult(False, "inaturalist", api_checked=False, api_called=False, message="No query available for iNaturalist")
        
        # Clean the query: remove (group), cultivar names, etc.
        query = self._clean_query(raw_query)

        try:
            params: dict[str, Any] = {
                "iconic_taxa": "Plantae",
                "photos": "true",
                "per_page": 5,
                "page": 1,
            }
            # Use cleaned query for taxon_name or general search
            if plant_data.get("scientific_name"):
                params["taxon_name"] = query
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
        timeout = aiohttp.ClientTimeout(total=10)
        async with self.session.get(url, params=params, timeout=timeout) as response:
            if response.status != 200:
                text = await response.text()
                self.last_error = f"iNaturalist HTTP {response.status}: {text[:200]}"
                return None
            return await response.json(content_type=None)

    def _clean_query(self, query: str) -> str:
        """Clean scientific/common name for iNaturalist search.
        
        Remove:
        - (group) suffix from genus groups
        - 'Cultivar Name' in quotes
        - Cultivar suffixes like 'Neon', 'Golden', etc.
        """
        # Remove (group), (species), etc.
        query = re.sub(r'\s*\([^)]+\)\s*', ' ', query)
        
        # Remove quoted cultivar names: 'Neon', 'Golden Pothos', etc.
        query = re.sub(r"\s*'[^']+'\s*", ' ', query)
        
        # Trim and collapse multiple spaces
        query = ' '.join(query.split())
        
        return query.strip()

    def _normalize(self, payload: dict[str, Any], query: str) -> dict[str, Any]:
        """Normalize iNaturalist observations."""
        results = payload.get("results") or []
        photos: list[dict[str, Any]] = []

        for item in results[:5]:
            for photo in item.get("photos") or []:
                # Use larger photo sizes: large > medium > original > square
                url = (
                    photo.get("large_url") 
                    or photo.get("medium_url") 
                    or photo.get("original_url")
                    or photo.get("url")
                )
                if url:
                    photos.append({
                        "url": url.replace("/square.", "/large."),  # Force large size
                        "license_code": photo.get("license_code"),
                        "attribution": photo.get("attribution"),
                    })

        return {
            "provider": "inaturalist",
            "query": query,
            "observation_count": payload.get("total_results", len(results)),
            "photos": photos[:10],
            "updated_at": datetime.now().isoformat(),
        }
