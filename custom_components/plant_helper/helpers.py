"""Shared helpers for Plant Helper.

Provider-payload parsing used by the config flow when caching species from the
enrichment providers. (Threshold/entity-resolution helpers were removed with the
v3 algorithm; the v4 engine derives everything from learned baselines.)
"""

from __future__ import annotations

from typing import Any


def extract_species_key(data: dict[str, Any], fallback: str) -> str:
    """Extract a stable species key from a provider payload."""
    for key in (
        "species",
        "scientific_name",
        "scientificName",
        "latin_name",
        "latinName",
        "name",
    ):
        value = data.get(key)
        if isinstance(value, list) and value and str(value[0]).strip():
            return str(value[0]).strip()
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback.strip()


def extract_common_name(data: dict[str, Any], fallback: str) -> str:
    """Extract a display common name from a provider payload."""
    for key in ("common_name", "commonName", "common", "name"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback.strip()


def get_linked_entity(plant_data: dict[str, Any], key: str) -> str | None:
    """Return a configured linked entity from current or legacy plant records."""
    containers = [plant_data.get("entities"), plant_data.get("sensors"), plant_data]
    aliases = {
        "moisture": ("moisture", "soil_moisture"),
        "temperature": ("temperature", "soil_temperature", "soil_temp"),
        "lux": ("lux", "room_lux"),
        "air_humidity": ("air_humidity", "humidity"),
        "battery": ("battery", "battery_entity"),
    }
    for container in containers:
        if not isinstance(container, dict):
            continue
        for candidate in aliases.get(key, (key,)):
            value = container.get(candidate)
            if isinstance(value, str) and value:
                return value
    return None
