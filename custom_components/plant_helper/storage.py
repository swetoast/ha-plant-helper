"""Storage management for Plant Helper."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    STORAGE_KEY,
    STORAGE_VERSION,
    ATTR_SPECIES,
    ATTR_COMMON_NAME,
    ATTR_THRESHOLDS,
    ATTR_TIPS,
    ATTR_FACTS,
)

_LOGGER = logging.getLogger(__name__)


class PlantStorage:
    """Handle storage of plant data."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize storage."""
        self.hass = hass
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._data: dict[str, Any] = {
            "plants": {},
            "user_plants": {},
        }

    async def async_load(self) -> None:
        """Load data from storage, recovering safely from unreadable data."""
        try:
            data = await self._store.async_load()
        except Exception:  # noqa: BLE001
            _LOGGER.exception(
                "Failed to load plant storage; using an empty in-memory store"
            )
            data = None
        if isinstance(data, dict):
            plants = data.get("plants")
            user_plants = data.get("user_plants")
            self._data = {
                "plants": plants if isinstance(plants, dict) else {},
                "user_plants": user_plants if isinstance(user_plants, dict) else {},
            }
        else:
            if data is not None:
                _LOGGER.error(
                    "Plant storage payload is malformed; using an empty in-memory store"
                )
            self._data = {"plants": {}, "user_plants": {}}
        _LOGGER.debug(
            "Loaded plant storage: %s cached plants, %s configured plants",
            len(self._data["plants"]),
            len(self._data["user_plants"]),
        )

    async def async_save(self) -> None:
        """Save data to storage."""
        await self._store.async_save(self._data)
        _LOGGER.debug("Saved plant storage")

    async def async_add_plant(
        self,
        species: str,
        plant_data: dict[str, Any],
    ) -> bool:
        """Add or update a plant in the cached species database."""
        if not species:
            _LOGGER.error("Cannot add plant without species name")
            return False

        self._data.setdefault("plants", {})

        self._data["plants"][species] = {
            ATTR_SPECIES: species,
            ATTR_COMMON_NAME: plant_data.get(ATTR_COMMON_NAME, species),
            ATTR_THRESHOLDS: plant_data.get(ATTR_THRESHOLDS, {}),
            ATTR_TIPS: plant_data.get(
                ATTR_TIPS,
                {
                    "direct": [],
                    "seasonal": [],
                },
            ),
            ATTR_FACTS: plant_data.get(ATTR_FACTS, []),
            **plant_data,
        }

        await self.async_save()

        _LOGGER.info("Added/updated cached plant species: %s", species)
        return True

    async def async_remove_plant(self, species: str) -> bool:
        """Remove one plant species from the cached database."""
        self._data.setdefault("plants", {})

        if species in self._data["plants"]:
            del self._data["plants"][species]
            await self.async_save()

            _LOGGER.info("Removed cached plant species: %s", species)
            return True

        return False

    def get_plant(self, species: str) -> dict[str, Any] | None:
        """Get plant data by species."""
        self._data.setdefault("plants", {})
        return self._data["plants"].get(species)

    def get_plant_by_name(self, search_name: str) -> dict[str, Any] | None:
        """Get plant data by common name or species.

        This is used by the API wrapper before making API calls.
        """
        self._data.setdefault("plants", {})

        search_lower = search_name.lower().strip()

        exact_name_match = None
        partial_match = None

        for species, plant_data in self._data["plants"].items():
            common_name = str(plant_data.get("common_name", "")).lower()

            if species.lower() == search_lower:
                return plant_data

            if common_name and common_name == search_lower:
                exact_name_match = plant_data

            if not partial_match and (
                search_lower in species.lower()
                or (common_name and search_lower in common_name)
            ):
                partial_match = plant_data

        return exact_name_match or partial_match

    def get_all_plants(self) -> dict[str, dict[str, Any]]:
        """Get all cached plants in the database."""
        self._data.setdefault("plants", {})
        return self._data["plants"]

    async def async_add_user_plant(
        self,
        plant_id: str,
        species: str,
        custom_name: str | None = None,
        entities: dict[str, str] | None = None,
    ) -> bool:
        """Add a user's configured plant instance."""
        self._data.setdefault("plants", {})
        self._data.setdefault("user_plants", {})

        if species not in self._data["plants"]:
            _LOGGER.error(
                "Cannot add user plant: species '%s' not in database",
                species,
            )
            return False

        if plant_id in self._data["user_plants"]:
            _LOGGER.warning("Configured plant '%s' already exists, updating", plant_id)

        self._data["user_plants"][plant_id] = {
            "species": species,
            "custom_name": custom_name or species,
            "entities": entities or {},
            "added_date": dt_util.now().isoformat(),
        }

        await self.async_save()

        _LOGGER.info("Added configured plant: %s species=%s", plant_id, species)
        return True

    async def async_remove_user_plant(self, plant_id: str) -> bool:
        """Remove a user's configured plant instance."""
        self._data.setdefault("user_plants", {})

        if plant_id in self._data["user_plants"]:
            del self._data["user_plants"][plant_id]
            await self.async_save()

            _LOGGER.info("Removed configured plant: %s", plant_id)
            return True

        return False

    async def async_update_user_plant(
        self,
        plant_id: str,
        updates: dict[str, Any],
    ) -> bool:
        """Update configured plant data."""
        self._data.setdefault("user_plants", {})

        if plant_id not in self._data["user_plants"]:
            _LOGGER.error("Cannot update configured plant '%s': not found", plant_id)
            return False

        self._data["user_plants"][plant_id].update(updates)
        await self.async_save()

        _LOGGER.debug(
            "Updated configured plant '%s': %s",
            plant_id,
            updates.keys(),
        )
        return True

    def get_user_plant(self, plant_id: str) -> dict[str, Any] | None:
        """Get one configured plant instance."""
        self._data.setdefault("user_plants", {})
        return self._data["user_plants"].get(plant_id)

    def get_all_user_plants(self) -> dict[str, dict[str, Any]]:
        """Get all configured plant instances."""
        self._data.setdefault("user_plants", {})
        return self._data["user_plants"]