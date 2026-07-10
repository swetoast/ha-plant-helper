"""Pure config-flow logic: field keys, validation, record building, id slugs.

Kept free of Home Assistant imports so the validation the setup relies on can be
unit-tested. `config_flow.py` supplies the live sensor state to `validate_plant`
and otherwise just renders forms around these helpers.
"""

from __future__ import annotations

import re
from typing import Any

# Form field keys (also the storage "entities" dict keys).
CONF_NAME = "name"
CONF_SPECIES = "species"
CONF_MOISTURE = "soil_moisture"
CONF_SOIL_TEMP = "soil_temperature"
CONF_LUX = "lux"
CONF_BATTERY = "battery"
CONF_PLACEMENT = "placement"
CONF_PROFILE = "profile"
CONF_CUSTOM_MULTIPLIER = "custom_multiplier"
CONF_RAIN_LIMIT_MM = "rain_limit_mm"
CONF_PLANT_ID = "plant_id"

ENTITY_KEYS = (CONF_MOISTURE, CONF_SOIL_TEMP, CONF_LUX, CONF_BATTERY)

DEFAULT_PLACEMENT = "indoor"
DEFAULT_PROFILE = "balanced"
DEFAULT_RAIN_LIMIT_MM = 1.0
PROFILE_CUSTOM = "custom"

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
