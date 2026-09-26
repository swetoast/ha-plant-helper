from __future__ import annotations

from datetime import datetime

from homeassistant.components.image import ImageEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import PlantHelperConfigEntry
from .domain.entity_contract import SPECIES_IMAGE_KEY, unique_id
from .domain.runtime import RuntimePlant
from .entity import async_setup_plant_platform, device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PlantHelperConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one species photo entity per plant and track live changes."""
    runtime = entry.runtime_data
    async_setup_plant_platform(
        hass,
        entry,
        async_add_entities,
        "image",
        lambda plant: [PlantHelperImage(hass, entry.entry_id, runtime, plant)],
    )


class PlantHelperImage(ImageEntity):
    """The plant's species photo, served from the local image cache."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_content_type = "image/webp"

    def __init__(self, hass, entry_id, runtime, plant: RuntimePlant) -> None:
        super().__init__(hass)
        self._runtime = runtime
        self._plant = plant
        self.plant_uuid = plant.plant_uuid
        self._attr_unique_id = unique_id(entry_id, plant.plant_uuid, SPECIES_IMAGE_KEY)
        # The photo is the plant device's primary entity: no entity name, so the
        # entity id is image.<plant> and the friendly name is the plant's name.
        self._attr_name = None
        self._attr_translation_key = SPECIES_IMAGE_KEY
        self._attr_device_info = device_info(runtime, plant)

    @property
    def available(self) -> bool:
        return not self._plant.removing and self.plant_uuid in self._runtime.species_images

    @property
    def image_last_updated(self) -> datetime | None:
        cached = self._runtime.species_images.get(self.plant_uuid)
        return cached.created_at if cached is not None else None

    async def async_image(self) -> bytes | None:
        cached = self._runtime.species_images.get(self.plant_uuid)
        if cached is None:
            return None
        try:
            return await self.hass.async_add_executor_job(cached.path.read_bytes)
        except OSError:
            return None
