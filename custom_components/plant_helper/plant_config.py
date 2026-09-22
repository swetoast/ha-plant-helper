"""Pure config-flow logic: field keys, validation, record building, id slugs.

Kept free of Home Assistant imports so the validation the setup relies on can be
unit-tested. `config_flow.py` supplies the live sensor state to `validate_plant`
and otherwise just renders forms around these helpers.
"""

from __future__ import annotations

import math
import re
from typing import Any

from .const import (
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_OZONE_ENTITY,
    CONF_PERENUAL_ACCESS_LEVEL,
    CONF_PERENUAL_API_KEY,
    CONF_TREFLE_API_KEY,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    PERENUAL_ACCESS_FREE,
    PERENUAL_ACCESS_PAID,
)

# Form field keys (also the storage "entities" dict keys).
CONF_NAME = "name"
CONF_SPECIES = "species"
CONF_MOISTURE = "soil_moisture"
CONF_HUMIDITY = "humidity_sensor"  # distinct AIR-humidity sensor (advisory)
CONF_SOIL_TEMP = "soil_temperature"
CONF_LUX = "lux"
CONF_BATTERY = "battery"
CONF_PLACEMENT = "placement"
CONF_PROFILE = "profile"
CONF_CUSTOM_MULTIPLIER = "custom_multiplier"
CONF_RAIN_LIMIT_MM = "rain_limit_mm"
CONF_PLANT_ID = "plant_id"

ENTITY_KEYS = (
    CONF_MOISTURE,
    CONF_SOIL_TEMP,
    CONF_HUMIDITY,
    CONF_LUX,
    CONF_BATTERY,
)
CONFIGURABLE_ENTITY_KEYS = frozenset(
    {
        *ENTITY_KEYS,
        CONF_PLACEMENT,
        CONF_PROFILE,
        CONF_CUSTOM_MULTIPLIER,
        CONF_RAIN_LIMIT_MM,
    }
)

DEFAULT_PLACEMENT = "indoor"
DEFAULT_PROFILE = "balanced"
DEFAULT_RAIN_LIMIT_MM = 1.0
PROFILE_CUSTOM = "custom"

GLOBAL_OPTION_KEYS = frozenset(
    {
        CONF_LATITUDE,
        CONF_LONGITUDE,
        CONF_OZONE_ENTITY,
        CONF_PERENUAL_API_KEY,
        CONF_PERENUAL_ACCESS_LEVEL,
        CONF_TREFLE_API_KEY,
        CONF_UPDATE_INTERVAL,
    }
)


def normalize_global_options(values: Any) -> dict[str, Any]:
    """Normalize Global settings for setup, display, and persistence."""
    source = values if isinstance(values, dict) else {}
    normalized: dict[str, Any] = {
        CONF_PERENUAL_ACCESS_LEVEL: PERENUAL_ACCESS_FREE,
        CONF_UPDATE_INTERVAL: DEFAULT_UPDATE_INTERVAL,
    }

    def _bounded_number(key: str, minimum: float, maximum: float) -> None:
        value = source.get(key)
        if isinstance(value, bool):
            return
        try:
            number = float(value)
        except (TypeError, ValueError):
            return
        if math.isfinite(number) and minimum <= number <= maximum:
            normalized[key] = number

    _bounded_number(CONF_LATITUDE, -90.0, 90.0)
    _bounded_number(CONF_LONGITUDE, -180.0, 180.0)

    ozone_entity = source.get(CONF_OZONE_ENTITY)
    if isinstance(ozone_entity, str):
        ozone_entity = ozone_entity.strip()
        if ozone_entity.startswith("sensor.") and len(ozone_entity) > len("sensor."):
            normalized[CONF_OZONE_ENTITY] = ozone_entity

    for key in (CONF_PERENUAL_API_KEY, CONF_TREFLE_API_KEY):
        value = source.get(key)
        if isinstance(value, str) and (value := value.strip()):
            normalized[key] = value

    access_level = source.get(CONF_PERENUAL_ACCESS_LEVEL)
    if access_level in (PERENUAL_ACCESS_FREE, PERENUAL_ACCESS_PAID):
        normalized[CONF_PERENUAL_ACCESS_LEVEL] = access_level

    interval = source.get(CONF_UPDATE_INTERVAL)
    if not isinstance(interval, bool):
        try:
            interval_number = float(interval)
        except (TypeError, ValueError):
            interval_number = float(DEFAULT_UPDATE_INTERVAL)
        if math.isfinite(interval_number):
            normalized[CONF_UPDATE_INTERVAL] = max(60, min(3600, int(interval_number)))

    return normalized


def next_revision(value: Any) -> int:
    """Return a safe monotonically increasing options revision."""
    if isinstance(value, bool):
        return 1
    try:
        revision = int(value)
    except (TypeError, ValueError, OverflowError):
        return 1
    return max(0, revision) + 1


def replace_global_options(existing: Any, submitted: Any) -> dict[str, Any]:
    """Replace all Global settings while preserving unrelated internal options."""
    current = dict(existing) if isinstance(existing, dict) else {}
    options = {key: value for key, value in current.items() if key not in GLOBAL_OPTION_KEYS}
    options.update(normalize_global_options(submitted))
    options["_rev"] = next_revision(current.get("_rev"))
    return options

_SLUG_RE = re.compile(r"[^a-z0-9_]+")


def slug(name: str) -> str:
    """Lowercase ASCII slug (HA-independent) for a plant id base."""
    s = _SLUG_RE.sub("_", (name or "").strip().lower()).strip("_")
    return s or "plant"


def unique_plant_id(existing: Any, name: str) -> str:
    """A plant id derived from `name`, made unique against `existing` ids."""
    existing = set(existing or ())
    base = slug(name)
    pid = base
    i = 2
    while pid in existing:
        pid = f"{base}_{i}"
        i += 1
    return pid


def validate_plant(data: dict[str, Any], *, moisture_state: str | None) -> dict[str, str]:
    """Field -> error map for a plant form (empty means valid).

    `moisture_state` is the current state of the chosen moisture sensor (or None
    if unset/unknown); the caller fetches it from Home Assistant.
    """
    errors: dict[str, str] = {}

    if not (data.get(CONF_NAME) or "").strip():
        errors[CONF_NAME] = "name_required"

    if not data.get(CONF_MOISTURE):
        errors[CONF_MOISTURE] = "moisture_required"
    elif moisture_state not in (None, "unknown", "unavailable"):
        try:
            value = float(moisture_state)
            if not 0.0 <= value <= 100.0:
                errors[CONF_MOISTURE] = "moisture_out_of_range"
        except (TypeError, ValueError):
            errors[CONF_MOISTURE] = "moisture_not_numeric"

    if data.get(CONF_PROFILE) == PROFILE_CUSTOM:
        mult = data.get(CONF_CUSTOM_MULTIPLIER)
        try:
            if mult is None or not 0.0 < float(mult) <= 1.0:
                errors[CONF_CUSTOM_MULTIPLIER] = "custom_multiplier_range"
        except (TypeError, ValueError):
            errors[CONF_CUSTOM_MULTIPLIER] = "custom_multiplier_range"

    return errors


def split_record(data: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    """Validated form -> (display_name, species_key, entities dict).

    Species falls back to the plant name when omitted (v4: species is optional).
    """
    name = data[CONF_NAME].strip()
    species = (data.get(CONF_SPECIES) or "").strip() or name

    entities: dict[str, Any] = {}
    for key in ENTITY_KEYS:
        if data.get(key):
            entities[key] = data[key]
    entities[CONF_PLACEMENT] = data.get(CONF_PLACEMENT, DEFAULT_PLACEMENT)
    entities[CONF_PROFILE] = data.get(CONF_PROFILE, DEFAULT_PROFILE)
    entities[CONF_RAIN_LIMIT_MM] = data.get(CONF_RAIN_LIMIT_MM, DEFAULT_RAIN_LIMIT_MM)
    if data.get(CONF_PROFILE) == PROFILE_CUSTOM and data.get(CONF_CUSTOM_MULTIPLIER) is not None:
        entities[CONF_CUSTOM_MULTIPLIER] = float(data[CONF_CUSTOM_MULTIPLIER])
    return name, species, entities
