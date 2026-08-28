"""Shared base for Plant Helper entities.

Both platforms are thin readers of the coordinator's per-plant EngineResult;
this base holds the identity, device grouping, and result-lookup logic they
share so neither platform re-implements it.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import AUTHOR, DOMAIN


def hub_device_info(entry: ConfigEntry) -> DeviceInfo:
    """Device for hub-level entities (API diagnostics)."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="Plant Helper",
        manufacturer=AUTHOR,
        model="Plant care hub",
    )


class PlantEntity(CoordinatorEntity):
    """Common identity + result resolution for a single plant's entities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator,
        entry: ConfigEntry,
        plant_id: str,
        plant_name: str,
        key: str,
        label: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._plant_id = plant_id
        self._plant_name = plant_name
        self._attr_name = label
        self._attr_unique_id = f"{entry.entry_id}_{plant_id}_{key}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._plant_id)},
            name=self._plant_name,
            manufacturer=AUTHOR,
            model="Calibrated care",
            via_device=(DOMAIN, self._entry.entry_id),
        )

    @property
    def _result(self):
        """This plant's EngineResult, or None if not yet computed."""
        return (self.coordinator.data or {}).get(self._plant_id)

    @property
    def available(self) -> bool:
        return self._result is not None
