"""Enrichment normalisation (pure): merged provider data -> useful care context.

The three providers each contribute different useful fields:
  * Perenual  — watering frequency, sunlight, care level, cycle, toxicity, image.
  * Trefle    — temperature range (deg C), light scale, soil-humidity, edible.
  * iNaturalist — photos, common name, taxonomy.

The API layer merges them into one cached record per species. This module pulls
the genuinely useful, care-relevant fields out of that record and derives a
*suggested care profile*, which is how enrichment becomes meaningful: it can
recommend the dry_tolerant / balanced / moisture_loving profile for the plant.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SpeciesInfo:
    common_name: str | None = None
    scientific_name: str | None = None
    family: str | None = None
    watering: str | None = None            # Frequent | Average | Minimum
    sunlight: tuple[str, ...] = ()
    care_level: str | None = None
    cycle: str | None = None               # Perennial | Annual | ...
    maintenance: str | None = None
    growth_rate: str | None = None
    poisonous_to_pets: bool | None = None
    poisonous_to_humans: bool | None = None
    edible: bool | None = None
    temperature_min_c: float | None = None
    temperature_max_c: float | None = None
    soil_moisture_min: float | None = None
    soil_moisture_max: float | None = None
    soil_humidity_scale: float | None = None   # Trefle 0-10
    light_scale: float | None = None           # Trefle 0-10
    description: str | None = None
    image_url: str | None = None
    sources: tuple[str, ...] = ()

    @property
    def available(self) -> bool:
        return any((self.common_name, self.watering, self.care_level, self.temperature_min_c is not None))

    @property
    def pet_safe(self) -> bool | None:
        if self.poisonous_to_pets is None:
            return None
        return not self.poisonous_to_pets

    def as_attributes(self) -> dict[str, Any]:
        """Compact, non-null attribute dict for an entity."""
        out: dict[str, Any] = {}
        fields = {
            "common_name": self.common_name,
            "scientific_name": self.scientific_name,
            "family": self.family,
            "watering": self.watering,
            "sunlight": list(self.sunlight) or None,
            "care_level": self.care_level,
            "cycle": self.cycle,
            "maintenance": self.maintenance,
            "growth_rate": self.growth_rate,
            "pet_safe": self.pet_safe,
            "toxic_to_humans": self.poisonous_to_humans,
            "edible": self.edible,
            "ideal_temp_min_c": self.temperature_min_c,
            "ideal_temp_max_c": self.temperature_max_c,
            "image_url": self.image_url,
            "sources": list(self.sources) or None,
            "suggested_profile": suggested_profile(self),
        }
        for key, value in fields.items():
            if value is not None:
                out[key] = value
        return out


def _as_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in ("1", "true", "yes"):
        return True
    if text in ("0", "false", "no"):
        return False
    return None


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _image(record: dict[str, Any]) -> str | None:
    di = record.get("default_image")
    if isinstance(di, dict):
        return di.get("regular_url") or di.get("original_url") or di.get("medium_url")
    if isinstance(di, str) and di:
        return di
    if record.get("image_url"):
        return record["image_url"]
    photos = record.get("photos") or []
    if photos and isinstance(photos[0], dict):
        return photos[0].get("url")
    return None


def extract_species_info(record: dict[str, Any] | None) -> SpeciesInfo:
    """Pull the useful, care-relevant fields from a merged cache record."""
    if not record:
        return SpeciesInfo()

    thresholds = record.get("thresholds") or {}
    growth = record.get("growth") or {}
    sunlight = record.get("sunlight") or []
    if isinstance(sunlight, str):
        sunlight = [sunlight]

    sources = record.get("sources")
    if not sources:
        sources = [s for s in (record.get("provider"), record.get("source")) if s]

    return SpeciesInfo(
        common_name=record.get("common_name"),
        scientific_name=record.get("scientific_name"),
        family=record.get("family"),
        watering=record.get("watering"),
        sunlight=tuple(str(s) for s in sunlight),
        care_level=record.get("care_level"),
        cycle=record.get("cycle") or record.get("duration"),
        maintenance=record.get("maintenance"),
        growth_rate=record.get("growth_rate"),
        poisonous_to_pets=_as_bool(record.get("poisonous_to_pets")),
        poisonous_to_humans=_as_bool(record.get("poisonous_to_humans")),
        edible=_as_bool(record.get("edible")),
        temperature_min_c=_as_float(thresholds.get("temperature_min")),
        temperature_max_c=_as_float(thresholds.get("temperature_max")),
        soil_moisture_min=_as_float(thresholds.get("soil_moisture_min")),
        soil_moisture_max=_as_float(thresholds.get("soil_moisture_max")),
        soil_humidity_scale=_as_float(
            thresholds.get("trefle_soil_humidity_scale") or growth.get("soil_humidity")
        ),
        light_scale=_as_float(growth.get("light")),
        description=record.get("description"),
        image_url=_image(record),
        sources=tuple(dict.fromkeys(str(s) for s in sources)),
    )


def suggested_profile(info: SpeciesInfo) -> str | None:
    """Recommend a care profile from the species' known water needs.

    Priority: explicit watering frequency (Perenual) -> soil-moisture band
    (Perenual thresholds) -> soil-humidity scale (Trefle). Returns None when the
    data doesn't support a confident suggestion.
    """
    watering = (info.watering or "").strip().lower()
    if watering:
        if "min" in watering:
            return "dry_tolerant"
        if "frequent" in watering:
            return "moisture_loving"
        if "average" in watering:
            return "balanced"

    if info.soil_moisture_max is not None:
        if info.soil_moisture_max <= 50:
            return "dry_tolerant"
        if info.soil_moisture_max >= 70:
            return "moisture_loving"
        return "balanced"

    if info.soil_humidity_scale is not None:
        if info.soil_humidity_scale <= 3:
            return "dry_tolerant"
        if info.soil_humidity_scale >= 7:
            return "moisture_loving"
        return "balanced"

    return None
