"""Shared helpers for Plant Helper.

Centralizes logic that previously lived (and silently diverged) across
sensor.py, binary_sensor.py, plant_care_algorithms.py, __init__.py and
config_flow.py:

- Linked source-entity resolution (alias map + lookup)
- Species/common-name extraction from provider payloads
"""

from __future__ import annotations

from typing import Any

# Canonical superset of all aliases used historically by the various
# platforms. Keeping a single map here prevents the per-file drift that
# previously caused the binary_sensor and sensor platforms to resolve
# linked entities differently.
ENTITY_KEY_ALIASES: dict[str, tuple[str, ...]] = {
    "moisture": (
        "moisture",
        "moisture_entity",
        "humidity",
        "humidity_entity",
        "soil_moisture",
        "soil_humidity",
    ),
    "humidity": (
        "humidity",
        "humidity_entity",
        "moisture",
        "moisture_entity",
        "soil_moisture",
        "soil_humidity",
    ),
    "temperature": (
        "temperature",
        "temperature_entity",
        "temp",
        "temp_entity",
        "room_temperature",
        "soil_temperature",
    ),
    "temp": (
        "temp",
        "temp_entity",
        "temperature",
        "temperature_entity",
        "room_temperature",
        "soil_temperature",
    ),
    "lux": (
        "lux",
        "lux_entity",
        "light",
        "light_entity",
        "room_lux",
    ),
    "air_humidity": (
        "air_humidity",
        "air_humidity_entity",
        "room_humidity",
    ),
}


def get_linked_entity(plant_data: dict[str, Any], key: str) -> str | None:
    """Resolve a linked Home Assistant entity id for a logical sensor key."""
    entities = plant_data.get("entities", {}) if isinstance(plant_data, dict) else {}
    for alias in ENTITY_KEY_ALIASES.get(key, (key, f"{key}_entity")):
        value = entities.get(alias)
        if value:
            return str(value)
    return None


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
