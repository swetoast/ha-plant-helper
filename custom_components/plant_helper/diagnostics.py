"""Diagnostics download for the Plant Helper entry and for each plant device.

Provider keys and the location are redacted. Species image URLs are redacted
too: Perenual's are signed links that act as short-lived credentials.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry

from . import PlantHelperConfigEntry
from .const import DOMAIN

TO_REDACT = {"perenual_api_key", "trefle_api_key", "latitude", "longitude", "image_url"}
LEDGER_DAYS_SHOWN = 7


def _plant(runtime: Any, plant_uuid: str) -> dict[str, Any]:
    plant = runtime.plants.plants[plant_uuid]
    now = datetime.now(timezone.utc)
    history = runtime.temporal_history.get(plant_uuid)
    moisture_state = runtime.temporal_state.get(plant_uuid)
    ledger = runtime.temporal_daily.get(plant_uuid, {})
    learning = runtime.learning
    learned = None
    if learning is not None and plant_uuid in learning.placement:
        state = learning.state(plant_uuid)
        learned = {
            "placement": state.placement,
            "calibrating": state.calibrating,
            "baseline": state.baseline,
            "samples": state.active_samples,
        }
    return {
        "config": dict(plant.config),
        "published": dict(plant.state),
        "history": {
            "observations": len(history) if history is not None else 0,
            "confidence": history.confidence(now) if history is not None else None,
        },
        "moisture_state": (
            {
                field: getattr(moisture_state, field)
                for field in moisture_state.__dataclass_fields__
            }
            if moisture_state is not None
            else None
        ),
        "recent_days": [ledger[day].to_dict() for day in sorted(ledger)[-LEDGER_DAYS_SHOWN:]],
        "learning": learned,
        "species_image_cached": plant_uuid in runtime.species_images,
    }


def _integration(runtime: Any) -> dict[str, Any]:
    enrichment = runtime.source_enrichment
    return {
        "version": runtime.version,
        "providers": sorted(runtime.provider_adapters),
        "perenual_free": runtime.perenual_free,
        "provider_problems": dict(enrichment.problems) if enrichment else {},
        "species_records": (
            {
                key: {"status": entry.get("status"), "expires_at": entry.get("expires_at")}
                for key, entry in sorted(enrichment.cache.items())
            }
            if enrichment
            else {}
        ),
        "daylight": {
            "windows": len(runtime.ephemeris_windows),
            "fetched_at": runtime.ephemeris_fetched_at,
            "stale": runtime.ephemeris_stale,
        },
        "forecast_loaded": runtime.forecast_data is not None,
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: PlantHelperConfigEntry
) -> dict[str, Any]:
    runtime = entry.runtime_data
    return async_redact_data(
        {
            "options": dict(entry.options),
            "integration": _integration(runtime),
            "plants": {uuid: _plant(runtime, uuid) for uuid in sorted(runtime.plants.plants)},
        },
        TO_REDACT,
    )


async def async_get_device_diagnostics(
    hass: HomeAssistant, entry: PlantHelperConfigEntry, device: DeviceEntry
) -> dict[str, Any]:
    runtime = entry.runtime_data
    uuids = [ident for domain, ident in device.identifiers if domain == DOMAIN]
    plants = {uuid: _plant(runtime, uuid) for uuid in uuids if uuid in runtime.plants.plants}
    return async_redact_data(
        {"integration": _integration(runtime), "plants": plants}, TO_REDACT
    )
