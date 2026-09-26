from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import PlantHelperConfigEntry
from .domain.config import PROFILES
from .domain.entity_contract import CARE_PROFILE_KEY, suggested_entity_id, unique_id
from .domain.runtime import RuntimePlant
from .entity import CATEGORIES, async_setup_plant_platform, device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PlantHelperConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the care profile selector of every plant."""
    runtime = entry.runtime_data
    async_setup_plant_platform(
        hass,
        entry,
        async_add_entities,
        "select",
        lambda plant: [PlantHelperCareProfile(runtime, entry.entry_id, plant)],
    )


class PlantHelperCareProfile(SelectEntity):
    """The plant's care profile, changeable without opening the plant options."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_options = list(PROFILES)
    _attr_entity_category = CATEGORIES["config"]

    def __init__(self, runtime, entry_id: str, plant: RuntimePlant) -> None:
        self._runtime = runtime
        self._plant = plant
        self.plant_uuid = plant.plant_uuid
        display_name = str(plant.config.get("display_name", plant.plant_uuid))
        self._attr_unique_id = unique_id(entry_id, plant.plant_uuid, CARE_PROFILE_KEY)
        self._attr_suggested_object_id = suggested_entity_id(display_name, CARE_PROFILE_KEY)
        self._attr_name = "Care profile"
        self._attr_translation_key = CARE_PROFILE_KEY
        self._attr_device_info = device_info(runtime, plant)

    @property
    def available(self) -> bool:
        return not self._plant.removing

    @property
    def current_option(self) -> str | None:
        return self._plant.config.get("profile")

    async def async_select_option(self, option: str) -> None:
        await self._runtime.async_change_setting(self.plant_uuid, "profile", option)
