from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .domain.runtime import RuntimeCollection
from .domain.storage import PlantHelperStorage, StorageBackend


async def _async_noop(*_args: Any, **_kwargs: Any) -> None:
    """Complete an optional runtime hook without side effects."""


@dataclass(slots=True)
class PlantHelperRuntime:
    """Live integration state and operational flow callbacks."""

    plants: RuntimeCollection = field(default_factory=RuntimeCollection)
    platform_callbacks: dict[str, Any] = field(default_factory=dict)
    entities: dict[str, dict[str, Any]] = field(default_factory=dict)
    storage: PlantHelperStorage | None = None
    register_listeners: Any = _async_noop
    replace_listeners: Any = _async_noop
    evaluate: Any = _async_noop
    schedule_enrichment: Any = _async_noop
    schedule_reconciliation: Any = _async_noop
    handle_placement_change: Any = _async_noop
    handle_species_change: Any = _async_noop
    destination_baseline_complete: Any = lambda *_args, **_kwargs: False
    cancel_tasks: Any = _async_noop
    unsubscribe_listeners: Any = _async_noop
    block_evaluation: Any = _async_noop
    remove_entity_registry: Any = _async_noop
    verify_entities_gone: Any = _async_noop
    remove_device_registry: Any = _async_noop
    remove_owned_state: Any = _async_noop
    physical_processor: Any = None
    physical_subscriptions: Any = None
    cached_environment: Any = None
    learning: Any=None
    forecast_collector: Any = None
    air_quality_collector: Any = None
    environmental_snapshot: Any = None
    interpret_environment: Any = None
    species_enrichment: Any = None
    species_image_proxy: Any=None

    async def async_initialize(self, backend: StorageBackend) -> None:
        """Load persistent storage before platforms or option flows can run."""
        storage = PlantHelperStorage(backend)
        snapshot = await storage.async_load()
        self.storage = storage
        self.plants.load(snapshot.data["plants"])

    def require_storage(self) -> PlantHelperStorage:
        """Return initialized storage or fail with a precise internal error."""
        if self.storage is None:
            raise RuntimeError("plant_helper_storage_not_initialized")
        return self.storage
