from __future__ import annotations

from datetime import datetime

from homeassistant.components.image import ImageEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import PlantHelperConfigEntry
from .const import DOMAIN
from .domain.entity_contract import SPECIES_IMAGE_KEY, unique_id
from .domain.runtime import PlantSetChange, RuntimePlant


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PlantHelperConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one species photo entity per plant and track live changes."""
    runtime = entry.runtime_data
    known: set[str] = set()

    @callback
    def ensure_plant(plant_uuid: str) -> None:
        """Create this plant's image entity once, independent of event timing."""
        if plant_uuid in known:
            return
        plant = runtime.plants.plants.get(plant_uuid)
        if plant is None:
            return
        entity = PlantHelperImage(hass, entry.entry_id, runtime, plant)
        runtime.entities.setdefault(plant_uuid, {})["image"] = [entity]
        known.add(plant_uuid)
        async_add_entities([entity])

    @callback
    def handle(change: PlantSetChange) -> None:
        for plant_uuid in sorted(change.added):
            ensure_plant(plant_uuid)
        for plant_uuid in change.updated:
            for entity in runtime.entities.get(plant_uuid, {}).get("image", []):
                if entity.hass is not None:
                    entity.async_write_ha_state()
        for plant_uuid in change.removed:
            known.discard(plant_uuid)
            for entity in runtime.entities.get(plant_uuid, {}).pop("image", []):
                hass.async_create_task(entity.async_remove())
            if not runtime.entities.get(plant_uuid):
                runtime.entities.pop(plant_uuid, None)

    runtime.platform_callbacks["image"] = ensure_plant
    entry.async_on_unload(lambda: runtime.platform_callbacks.pop("image", None))
    entry.async_on_unload(runtime.plants.subscribe(handle))

    for plant_uuid in sorted(runtime.plants.plants):
        ensure_plant(plant_uuid)


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
        display_name = str(plant.config.get("display_name", plant.plant_uuid))
        self._attr_unique_id = unique_id(entry_id, plant.plant_uuid, SPECIES_IMAGE_KEY)
        # The photo is the plant device's primary entity: no entity name, so the
        # entity id is image.<plant> and the friendly name is the plant's name.
        self._attr_name = None
        self._attr_icon = "mdi:image"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, plant.plant_uuid)},
            "name": display_name,
            "manufacturer": "Plant Helper",
            "model": "Plant",
        }

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
