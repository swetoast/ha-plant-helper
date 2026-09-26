from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .const import DOMAIN
from .runtime import PlantHelperRuntime
from .services import async_register_services

PLATFORMS = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.IMAGE,
    Platform.EVENT,
    Platform.SELECT,
    Platform.NUMBER,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

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


async def async_setup(hass: HomeAssistant, _config: ConfigType) -> bool:
    """Register service actions once, independent of config entries."""
    async_register_services(hass)
    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: PlantHelperConfigEntry
) -> bool:
    """Load storage and runtime before forwarding entity platforms."""
    entry.runtime_data=PlantHelperRuntime()
    entry.runtime_data.version = str((await async_get_integration(hass, DOMAIN)).version)
    await entry.runtime_data.async_initialize(
        HomeAssistantStorageBackend(hass, entry.entry_id)
    )
    await entry.runtime_data.async_configure_enrichment(hass, entry.options)
    await entry.runtime_data.async_configure_weather(hass, entry.options)
    await entry.runtime_data.async_configure_temporal(hass, entry.entry_id)
    await entry.runtime_data.async_configure_images(hass)
    await entry.runtime_data.async_configure_learning()
    await entry.runtime_data.async_start(hass, entry.entry_id)
    entry.runtime_data.prune_retired_entities()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await entry.runtime_data.reconcile_pending_removals()
    return True


async def async_remove_entry(
    hass: HomeAssistant, entry: PlantHelperConfigEntry
) -> None:
    """Clear Plant Helper repair issues when the integration is removed."""
    registry = ir.async_get(hass)
    for domain, issue_id in list(registry.issues):
        if domain == DOMAIN:
            ir.async_delete_issue(hass, DOMAIN, issue_id)


async def async_unload_entry(
    hass: HomeAssistant, entry: PlantHelperConfigEntry
) -> bool:
    """Unload platforms and release runtime subscriptions."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_unload()
    return unloaded
