"""Plant Helper service actions."""
from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN

SERVICE_RELEARN = "relearn"

RELEARN_SCHEMA = vol.Schema(
    {vol.Optional("device_id"): vol.All(cv.ensure_list, [cv.string])},
    extra=vol.ALLOW_EXTRA,  # other target keys (area, entity) are ignored
)


def async_register_services(hass: HomeAssistant) -> None:
    """Register the integration's service actions once per Home Assistant."""

    async def relearn(call: ServiceCall) -> None:
        device_ids = call.data.get("device_id") or []
        if not device_ids:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="no_plant_selected"
            )
        registry = dr.async_get(hass)
        runtimes = [
            entry.runtime_data
            for entry in hass.config_entries.async_entries(DOMAIN)
            if entry.state is ConfigEntryState.LOADED
        ]
        targets = []
        for device_id in device_ids:
            device = registry.async_get(device_id)
            uuids = [ident for domain, ident in (device.identifiers if device else ()) if domain == DOMAIN]
            owner = next(
                (
                    (runtime, uuid)
                    for runtime in runtimes
                    for uuid in uuids
                    if uuid in runtime.plants.plants
                ),
                None,
            )
            if owner is None:
                raise ServiceValidationError(
                    translation_domain=DOMAIN, translation_key="not_a_plant"
                )
            targets.append(owner)
        # Validate every target before changing any plant.
        for runtime, plant_uuid in targets:
            await runtime.async_relearn(plant_uuid)

    hass.services.async_register(DOMAIN, SERVICE_RELEARN, relearn, schema=RELEARN_SCHEMA)
