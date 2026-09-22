from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .const import DOMAIN
from .domain.runtime import RuntimeCollection
from .domain.storage import PlantHelperStorage, StorageBackend
from .physical import PhysicalSubscriptions
from .domain.physical import PlantPhysicalProcessor
from .domain.remove_plant import (
    RemoveHooks,
    RemoveResult,
    async_reconcile_pending_removals,
    async_remove_plant,
)

_LOGGER = logging.getLogger(__name__)

_PROFILE_BANDS: dict[str, tuple[float, float]] = {
    "dry": (15.0, 45.0),
    "balanced": (25.0, 65.0),
    "moist": (40.0, 80.0),
    "custom": (25.0, 65.0),
}
_SOURCE_TO_STATE = {
    "soil_moisture": "moisture",
    "soil_temperature": "temperature",
    "lux": "light",
    "humidity_sensor": "humidity",
    "battery": "battery",
}


@dataclass(slots=True)
class PlantHelperRuntime:
    """Live Home Assistant runtime for Plant Helper."""

    plants: RuntimeCollection = field(default_factory=RuntimeCollection)
    platform_callbacks: dict[str, Any] = field(default_factory=dict)
    entities: dict[str, dict[str, Any]] = field(default_factory=dict)
    storage: PlantHelperStorage | None = None
    hass: HomeAssistant | None = None
    entry_id: str | None = None
    physical_processor: PlantPhysicalProcessor | None = None
    physical_subscriptions: PhysicalSubscriptions | None = None
    learning: Any = None
    species_image_proxy: Any = None
    _blocked: set[str] = field(default_factory=set)

    async def async_initialize(self, backend: StorageBackend) -> None:
        """Load persistent storage before platforms are forwarded."""
        storage = PlantHelperStorage(backend)
        snapshot = await storage.async_load()
        self.storage = storage
        self.plants.load(snapshot.data["plants"])

    async def async_start(self, hass: HomeAssistant, entry_id: str) -> None:
        """Connect stored plants to current Home Assistant source states."""
        self.hass = hass
        self.entry_id = entry_id
        self.physical_processor = PlantPhysicalProcessor(
            self.plants,
            self.evaluate,
            lambda _plant_uuid: {},
        )
        self.physical_subscriptions = PhysicalSubscriptions(
            hass, self.physical_processor
        )
        for plant_uuid, plant in self.plants.plants.items():
            await self.register_listeners(plant_uuid, plant.config)
            await self.evaluate(plant_uuid)

    def require_storage(self) -> PlantHelperStorage:
        if self.storage is None:
            raise RuntimeError("plant_helper_storage_not_initialized")
        return self.storage

    def _read_source(self, entity_id: str | None) -> Any:
        if self.hass is None or not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        return None if state is None else state.state

    async def register_listeners(
        self, plant_uuid: str, config: dict[str, Any]
    ) -> None:
        """Seed values and subscribe to every configured physical source."""
        if self.physical_subscriptions is None or self.physical_processor is None:
            raise RuntimeError("physical_runtime_not_started")
        self.physical_subscriptions.replace(plant_uuid, config)
        for source_key in _SOURCE_TO_STATE:
            entity_id = config.get(source_key)
            if entity_id:
                self.physical_processor.accept(
                    plant_uuid, source_key, self._read_source(entity_id)
                )

    async def replace_listeners(
        self, plant_uuid: str, config: dict[str, Any]
    ) -> None:
        await self.register_listeners(plant_uuid, config)

    async def evaluate(
        self, plant_uuid: str, _environment: Any = None
    ) -> None:
        """Produce stable user-facing states from current physical values."""
        plant = self.plants.plants.get(plant_uuid)
        if plant is None or plant.removing or plant_uuid in self._blocked:
            return

        state = plant.state
        moisture = state.get("moisture")
        profile = str(plant.config.get("profile", "balanced"))
        low, high = _PROFILE_BANDS.get(profile, _PROFILE_BANDS["balanced"])

        if moisture is None:
            care_status = "waiting_for_data"
            summary = "Waiting for a valid moisture reading"
            reason = "moisture_unavailable"
            attention = False
            health = "unknown"
        elif moisture < low:
            care_status = "water_soon"
            summary = "Soil moisture is below the selected care profile"
            reason = "soil_dry"
            attention = True
            health = "needs_water"
        elif moisture > high:
            care_status = "too_wet"
            summary = "Soil moisture is above the selected care profile"
            reason = "soil_wet"
            attention = True
            health = "too_wet"
        else:
            care_status = "normal"
            summary = "Soil moisture is within the selected care profile"
            reason = "moisture_in_range"
            attention = False
            health = "good"

        state["care_status"] = care_status
        state["care_status_attributes"] = {
            "summary": summary,
            "reason": reason,
        }
        state["health"] = health
        state["health_attributes"] = {"summary": summary}
        state["needs_attention"] = attention
        state["needs_attention_attributes"] = {
            "reason": reason if attention else None
        }
        state["calibration"] = "not_configured"
        state["calibration_attributes"] = {"progress": 0}

        species = plant.config.get("species")
        if species:
            state["species_context"] = str(species)
            state["species_context_attributes"] = {
                "scientific_name": str(species)
            }

        self.plants.notify_updated(plant_uuid)

    async def schedule_enrichment(self, *_args: Any) -> None:
        """Keep optional enrichment isolated from core plant operation."""

    async def schedule_reconciliation(self, plant_uuid: str) -> None:
        plant = self.plants.plants.get(plant_uuid)
        if plant is not None:
            await self.register_listeners(plant_uuid, plant.config)
            await self.evaluate(plant_uuid)

    async def handle_placement_change(self, *_args: Any) -> None:
        """Placement-specific providers remain optional in this patch line."""

    async def handle_species_change(self, plant_uuid: str, *_args: Any) -> None:
        await self.evaluate(plant_uuid)

    def destination_baseline_complete(self, *_args: Any) -> bool:
        return False

    async def cancel_tasks(self, plant_uuid: str) -> None:
        if self.physical_processor is not None:
            self.physical_processor.block(plant_uuid)

    async def unsubscribe_listeners(self, plant_uuid: str) -> None:
        if self.physical_subscriptions is not None:
            self.physical_subscriptions.unsubscribe(plant_uuid)

    async def block_evaluation(self, plant_uuid: str) -> None:
        self._blocked.add(plant_uuid)
        if self.physical_processor is not None:
            self.physical_processor.block(plant_uuid)

    def _owns_registry_entity(self, entity: Any, plant_uuid: str) -> bool:
        if entity.platform != DOMAIN:
            return False
        if self.entry_id is not None and entity.config_entry_id != self.entry_id:
            return False
        return entity.unique_id.startswith(f"{self.entry_id}_{plant_uuid}_")

    async def remove_loaded_entities(self, plant_uuid: str) -> None:
        """Remove attached platform entities and tolerate not-yet-added entities."""
        platform_entities = self.entities.pop(plant_uuid, {})
        for entities in platform_entities.values():
            for entity in tuple(entities):
                if entity.hass is not None:
                    await entity.async_remove()

    async def remove_entity_registry(self, plant_uuid: str) -> None:
        if self.hass is None:
            return
        registry = er.async_get(self.hass)
        for entity in list(registry.entities.values()):
            if self._owns_registry_entity(entity, plant_uuid):
                registry.async_remove(entity.entity_id)

    async def verify_entities_gone(self, plant_uuid: str) -> bool:
        if self.hass is None:
            return True
        registry = er.async_get(self.hass)
        return not any(
            self._owns_registry_entity(entity, plant_uuid)
            for entity in registry.entities.values()
        )

    async def remove_device_registry(self, plant_uuid: str) -> None:
        if self.hass is None:
            return
        registry = dr.async_get(self.hass)
        device = registry.async_get_device(identifiers={(DOMAIN, plant_uuid)})
        if device is None:
            return
        entity_registry = er.async_get(self.hass)
        if any(
            entity.device_id == device.id
            for entity in entity_registry.entities.values()
        ):
            # Keep the device while any entity, including a foreign template
            # entity, still references it. Deleting it would leave an invalid
            # device_id in that entity's registry record.
            return
        registry.async_remove_device(device.id)

    async def remove_owned_state(self, plant_uuid: str) -> None:
        self.entities.pop(plant_uuid, None)
        self._blocked.discard(plant_uuid)

    def removal_hooks(self) -> RemoveHooks:
        return RemoveHooks(
            self.cancel_tasks,
            self.unsubscribe_listeners,
            self.block_evaluation,
            self.remove_loaded_entities,
            self.remove_entity_registry,
            self.verify_entities_gone,
            self.remove_device_registry,
            self.remove_owned_state,
        )

    async def remove_plant(
        self, plant_uuid: str, expected_revision: int
    ) -> RemoveResult:
        return await async_remove_plant(
            plant_uuid=plant_uuid,
            expected_revision=expected_revision,
            storage=self.require_storage(),
            runtime=self.plants,
            hooks=self.removal_hooks(),
        )

    async def reconcile_pending_removals(self) -> list[RemoveResult]:
        return await async_reconcile_pending_removals(
            storage=self.require_storage(),
            runtime=self.plants,
            hooks_factory=lambda _plant_uuid: self.removal_hooks(),
        )

    async def async_unload(self) -> None:
        """Release subscriptions, debounce tasks, and runtime references."""
        if self.physical_subscriptions is not None:
            self.physical_subscriptions.unload()
        self.platform_callbacks.clear()
        self.entities.clear()
        self._blocked.clear()
        self.plants.unload()
        self.physical_subscriptions = None
        self.physical_processor = None
        self.hass = None
        self.entry_id = None
