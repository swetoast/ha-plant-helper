from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from .runtime import PlantHelperRuntime

PLATFORMS=[Platform.SENSOR,Platform.BINARY_SENSOR]
type PlantHelperConfigEntry=ConfigEntry[PlantHelperRuntime]

async def async_setup_entry(hass: HomeAssistant, entry: PlantHelperConfigEntry) -> bool:
    entry.runtime_data=PlantHelperRuntime()
    await hass.config_entries.async_forward_entry_setups(entry,PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: PlantHelperConfigEntry) -> bool:
    unloaded=await hass.config_entries.async_unload_platforms(entry,PLATFORMS)
    if unloaded:
        entry.runtime_data.plants.unload()
    return unloaded
