from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .runtime import PlantHelperRuntime

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]
type PlantHelperConfigEntry = ConfigEntry[PlantHelperRuntime]


class HomeAssistantStorageBackend:
    """Adapt Home Assistant Store to the domain storage contract."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store[dict[str, Any]] = Store(
            hass, 1, f"{DOMAIN}.{entry_id}"
        )

    async def async_load(self) -> dict[str, Any] | None:
        """Load the persisted Plant Helper payload."""
        return await self._store.async_load()

    async def async_save(self, data: dict[str, Any]) -> None:
        """Persist the complete Plant Helper payload."""
        await self._store.async_save(data)


async def async_setup_entry(
    hass: HomeAssistant, entry: PlantHelperConfigEntry
) -> bool:
    """Load storage and runtime before forwarding entity platforms."""
    entry.runtime_data=PlantHelperRuntime()
    await entry.runtime_data.async_initialize(
        HomeAssistantStorageBackend(hass, entry.entry_id)
    )
    await entry.runtime_data.async_start(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: PlantHelperConfigEntry
) -> bool:
    """Unload platforms and release runtime subscriptions."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_unload()
    return unloaded
