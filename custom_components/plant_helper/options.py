"""Options flow for Plant Helper."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import OptionsFlow
from homeassistant.helpers import selector

from .config_flow import _global_schema, _plant_schema, _select
from .const import (
    CONF_PERENUAL_API_KEY,
    CONF_TREFLE_API_KEY,
    DEFAULT_PLACEMENT,
    DOMAIN,
)
from .plant_config import (
    CONF_MOISTURE,
    CONF_NAME,
    CONF_PLACEMENT,
    CONF_PLANT_ID,
    CONF_SPECIES,
    split_record,
    unique_plant_id,
    validate_plant,
)

_LOGGER = logging.getLogger(__name__)


class PlantHelperOptionsFlow(OptionsFlow):
    """Add / edit / remove plants and edit global settings."""

    def __init__(self) -> None:
        self._edit_id: str | None = None

    # -- helpers --
    def _runtime(self) -> dict[str, Any]:
        """The live per-entry runtime data (storage, learned, samples, coordinator)."""
        return self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id, {})

    async def _load_storage(self) -> Any:
        """Return the RUNNING storage instance so mutations use one source of truth.

        Using a separate instance risks a stale copy being written back (e.g. on
        unload), which previously resurrected removed plants. Falls back to a
        fresh load only if the integration isn't currently set up.
        """
        storage = self._runtime().get("storage")
        if storage is not None:
            return storage
        from .storage import PlantStorage

        storage = PlantStorage(self.hass)
        await storage.async_load()
        return storage

    def _finish(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        """Close the options flow and trigger exactly one reload.

        Plant data lives in storage, so a mutation wouldn't otherwise change the
        entry options (no reload). Bumping a revision nonce guarantees the
        options-update listener fires once — deterministically, and without the
        double reload a manual reload-plus-changed-options would cause.
        """
        options = {**self.config_entry.options}
        if extra:
            options.update(extra)
        options["_rev"] = int(self.config_entry.options.get("_rev", 0)) + 1
        return self.async_create_entry(title="", data=options)

    def _remove_device(self, plant_id: str) -> None:
        """Delete the plant's entities and device from Home Assistant registries."""
        from homeassistant.helpers import device_registry as dr
        from homeassistant.helpers import entity_registry as er

        entity_registry = er.async_get(self.hass)
        unique_prefix = f"{self.config_entry.entry_id}_{plant_id}_"
        for entity in list(entity_registry.entities.values()):
            if (
                entity.platform == DOMAIN
                and entity.config_entry_id == self.config_entry.entry_id
                and entity.unique_id.startswith(unique_prefix)
            ):
                entity_registry.async_remove(entity.entity_id)

        device_registry = dr.async_get(self.hass)
        device = device_registry.async_get_device(identifiers={(DOMAIN, plant_id)})
        if device is not None:
            device_registry.async_remove_device(device.id)

    async def _purge_plant(self, storage: Any, plant_id: str) -> None:
        """Remove every trace of a plant: config, learned state, samples, device.

        Persisted immediately so the deletion survives the subsequent reload and
        nothing about the plant is left behind in Home Assistant.
        """
        await storage.async_remove_user_plant(plant_id)  # persists immediately

        runtime = self._runtime()
        learned = runtime.get("learned")
        if learned is not None:
            from .learned_store import remove_plant

            remove_plant(learned.data, plant_id)
            await learned.async_save()

        samples = runtime.get("samples")
        if samples is not None:
            from .sample_store import clear_key_prefix

            clear_key_prefix(samples.data, f"plant:{plant_id}:")
            await samples.async_save()

        # Drop it from the live coordinator too, so a cycle firing before the
        # reload can't re-create its learned/sample data.
        coordinator = runtime.get("coordinator")
        if coordinator is not None:
            getattr(coordinator, "_plants", {}).pop(plant_id, None)
            getattr(coordinator, "_enrichment", {}).pop(plant_id, None)

        self._remove_device(plant_id)

    def _moisture_state(self, data: dict[str, Any]) -> str | None:
        entity = data.get(CONF_MOISTURE)
        state = self.hass.states.get(entity) if entity else None
        return state.state if state is not None else None

    # -- menu --
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "add_plant",
                "edit_plant_select",
                "remove_plant",
                "global_settings",
            ],
        )

    # -- add --
    async def async_step_add_plant(self, user_input: dict[str, Any] | None = None) -> dict[str, Any]:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = validate_plant(user_input, moisture_state=self._moisture_state(user_input))
            if not errors:
                storage = await self._load_storage()
                name, species, entities = split_record(user_input)
                await self._ensure_species_stub(storage, species)
                plant_id = unique_plant_id(storage.get_all_user_plants(), name)
                await storage.async_add_user_plant(
                    plant_id, species=species, custom_name=name, entities=entities
                )
                return self._finish()
        return self.async_show_form(
            step_id="add_plant",
            data_schema=_plant_schema(user_input),
            errors=errors,
        )

    async def _ensure_species_stub(self, storage: Any, species: str) -> None:
        """Ensure a cache entry exists so the plant can be stored.

        No API call here: the coordinator performs the real provider lookup on its
        first cycle after setup (so the calls are real, hit the coordinator's own
        client, and show up in the API diagnostic sensors). If the species is
        already cached with real data, that data is kept.
        """
        if storage.get_plant(species) is None:
            await storage.async_add_plant(species, {"common_name": species})

    # -- edit --
    async def async_step_edit_plant_select(self, user_input: dict[str, Any] | None = None) -> dict[str, Any]:
        storage = await self._load_storage()
        plants = storage.get_all_user_plants()
        if not plants:
            return self.async_abort(reason="no_plants")
        if user_input is not None:
            self._edit_id = user_input[CONF_PLANT_ID]
            return await self.async_step_edit_plant()
        return self.async_show_form(
            step_id="edit_plant_select",
            data_schema=vol.Schema({vol.Required(CONF_PLANT_ID): _select(sorted(plants))}),
        )

    async def async_step_edit_plant(self, user_input: dict[str, Any] | None = None) -> dict[str, Any]:
        storage = await self._load_storage()
        record = storage.get_user_plant(self._edit_id) if self._edit_id else None
        if not record:
            return self.async_abort(reason="plant_not_found")

        errors: dict[str, str] = {}
        if user_input is not None:
            errors = validate_plant(user_input, moisture_state=self._moisture_state(user_input))
            if not errors:
                name, species, entities = split_record(user_input)
                previous = record.get("entities") or {}
                old_placement = previous.get(CONF_PLACEMENT, DEFAULT_PLACEMENT)
                new_placement = entities.get(CONF_PLACEMENT, DEFAULT_PLACEMENT)
                merged = {**previous, **entities}
                await self._ensure_species_stub(storage, species)
                await storage.async_update_user_plant(
                    self._edit_id, {
                        "custom_name": name,
                        "species": species,
                        "entities": merged,
                    }
                )
                if new_placement != old_placement:
                    runtime = self._runtime()
                    learned = runtime.get("learned")
                    samples = runtime.get("samples")
                    if learned is not None:
                        from .learned_store import set_timer, swap_placement

                        needs_calibration = swap_placement(
                            learned.data, self._edit_id, new_placement
                        )
                        if needs_calibration:
                            _LOGGER.info(
                                "Plant %s moved to %s without a complete baseline; "
                                "placement calibration will resume",
                                self._edit_id, new_placement,
                            )
                        else:
                            _LOGGER.info(
                                "Plant %s moved to %s and reused its complete baseline",
                                self._edit_id, new_placement,
                            )
                        for timer in ("dry", "wet", "cold", "warm"):
                            set_timer(learned.data, self._edit_id, timer, None)
                        await learned.async_save()
                    if samples is not None:
                        from .sample_store import clear_key_prefix

                        clear_key_prefix(samples.data, f"plant:{self._edit_id}:")
                        await samples.async_save()
                return self._finish()

        defaults = {
            CONF_NAME: record.get("custom_name") or self._edit_id,
            CONF_SPECIES: record.get("species"),
            **(record.get("entities") or {}),
        }
        return self.async_show_form(
            step_id="edit_plant",
            data_schema=_plant_schema(user_input or defaults),
            errors=errors,
        )

    # -- remove --
    async def async_step_remove_plant(self, user_input: dict[str, Any] | None = None) -> dict[str, Any]:
        storage = await self._load_storage()
        plants = storage.get_all_user_plants()
        if not plants:
            return self.async_abort(reason="no_plants")
        if user_input is not None:
            plant_id = user_input[CONF_PLANT_ID]
            await self._purge_plant(storage, plant_id)
            return self._finish()
        labels = {
            pid: f"{rec.get('custom_name') or pid}" for pid, rec in plants.items()
        }
        return self.async_show_form(
            step_id="remove_plant",
            data_schema=vol.Schema(
                {vol.Required(CONF_PLANT_ID): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[{"value": p, "label": l} for p, l in labels.items()],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )}
            ),
        )

    # -- global settings --
    async def async_step_global_settings(self, user_input: dict[str, Any] | None = None) -> dict[str, Any]:
        if user_input is not None:
            settings = dict(user_input)
            settings[CONF_PERENUAL_API_KEY] = (
                settings.get(CONF_PERENUAL_API_KEY) or ""
            ).strip()
            settings[CONF_TREFLE_API_KEY] = (
                settings.get(CONF_TREFLE_API_KEY) or ""
            ).strip()
            return self._finish(settings)
        return self.async_show_form(
            step_id="global_settings",
            data_schema=_global_schema(self.config_entry.options),
        )
