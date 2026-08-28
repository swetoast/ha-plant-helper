"""Plant Helper — configuration and options flow (v4, written from scratch).

Design goals:
  * Simple: adding a plant asks only for what the v4 engine actually uses —
    soil moisture (required), soil temperature, light, and battery. No species
    pre-caching, no room temp/humidity (the engine never reads those).
  * Powerful: full lifecycle from Options — add, edit, remove plants, and edit
    global settings (credentials, forecast source, ozone advisory, poll rate).
  * Validated: the required soil-moisture sensor must be provided and read as a
    plausible 0-100 % value; the custom profile requires a valid multiplier.
  * Smooth in HA: device-class-filtered entity pickers, a native options menu,
    pre-filled edit forms, and an automatic reload so changes take effect at once.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
    CONF_ENABLE_INATURALIST_ENRICHMENT,
    CONF_ENABLE_TREFLE_FALLBACK,
    CONF_FORECAST_ENTITY,
    CONF_OUTDOOR_DATA_SOURCE,
    CONF_OZONE_ENTITY,
    CONF_PERENUAL_API_KEY,
    CONF_RADIATION_SOURCE,
    CONF_TREFLE_API_KEY,
    CONF_UPDATE_INTERVAL,
    DEFAULT_ENABLE_INATURALIST_ENRICHMENT,
    DEFAULT_ENABLE_TREFLE_FALLBACK,
    DEFAULT_PLACEMENT,
    DEFAULT_RADIATION_SOURCE,
    DEFAULT_OUTDOOR_DATA_SOURCE,
    DEFAULT_PROFILE,
    DEFAULT_RAIN_LIMIT_MM,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    PLACEMENTS,
    RADIATION_SOURCES,
    OUTDOOR_DATA_SOURCES,
    PROFILES,
)
from .plant_config import (
    CONF_BATTERY,
    CONF_CUSTOM_MULTIPLIER,
    CONF_LUX,
    CONF_MOISTURE,
    CONF_NAME,
    CONF_PLANT_ID,
    CONF_PLACEMENT,
    CONF_PROFILE,
    CONF_RAIN_LIMIT_MM,
    CONF_SOIL_TEMP,
    CONF_SPECIES,
    split_record,
    unique_plant_id,
    validate_plant,
)
from .learned_store import remove_plant as learned_remove_plant
from .learned_store import set_timer as learned_set_timer
from .learned_store import swap_placement as learned_swap_placement
from .sample_store import clear_key_prefix
from .storage import PlantStorage

_LOGGER = logging.getLogger(__name__)



# --- selectors ------------------------------------------------------------

def _sensor(device_classes: list[str] | None = None) -> selector.EntitySelector:
    cfg: dict[str, Any] = {"domain": "sensor"}
    if device_classes:
        cfg["device_class"] = device_classes
    return selector.EntitySelector(selector.EntitySelectorConfig(**cfg))


def _select(options: list[str]) -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options, mode=selector.SelectSelectorMode.DROPDOWN
        )
    )


def _optional(key: str, current: Any) -> Any:
    """vol.Optional with a pre-filled suggested value when editing."""
    if current in (None, ""):
        return vol.Optional(key)
    return vol.Optional(key, description={"suggested_value": current})


# --- schemas --------------------------------------------------------------

def _plant_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """The add/edit plant form. `defaults` pre-fills it when editing."""
    d = defaults or {}
    moisture = d.get(CONF_MOISTURE)
    name_field = (
        vol.Required(CONF_NAME, default=d[CONF_NAME])
        if d.get(CONF_NAME)
        else vol.Required(CONF_NAME)
    )
    moisture_field = (
        vol.Required(CONF_MOISTURE, description={"suggested_value": moisture})
        if moisture
        else vol.Required(CONF_MOISTURE)
    )
    return vol.Schema(
        {
            name_field: selector.TextSelector(),
            _optional(CONF_SPECIES, d.get(CONF_SPECIES)): selector.TextSelector(),
            vol.Required(CONF_PLACEMENT, default=d.get(CONF_PLACEMENT, DEFAULT_PLACEMENT)): _select(PLACEMENTS),
            vol.Required(CONF_PROFILE, default=d.get(CONF_PROFILE, DEFAULT_PROFILE)): _select(PROFILES),
            vol.Optional(
                CONF_CUSTOM_MULTIPLIER,
                description={"suggested_value": d.get(CONF_CUSTOM_MULTIPLIER)},
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0.05, max=1.0, step=0.05, mode="box")
            ),
            # Sensors — moisture is required; the rest are optional but enable
            # more of the model (see step description).
            moisture_field: _sensor(["moisture", "humidity"]),
            _optional(CONF_SOIL_TEMP, d.get(CONF_SOIL_TEMP)): _sensor(["temperature"]),
            _optional(CONF_LUX, d.get(CONF_LUX)): _sensor(["illuminance"]),
            _optional(CONF_BATTERY, d.get(CONF_BATTERY)): _sensor(),  # categorical ok
            vol.Optional(
                CONF_RAIN_LIMIT_MM,
                default=float(d.get(CONF_RAIN_LIMIT_MM, DEFAULT_RAIN_LIMIT_MM) or DEFAULT_RAIN_LIMIT_MM),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0.0, max=50.0, step=0.5, mode="box")
            ),
        }
    )


def _global_schema(options: dict[str, Any] | None = None) -> vol.Schema:
    o = options or {}
    return vol.Schema(
        {
            _optional(CONF_FORECAST_ENTITY, o.get(CONF_FORECAST_ENTITY)):
                selector.EntitySelector(selector.EntitySelectorConfig(domain=["weather", "sensor"])),
            _optional(CONF_OZONE_ENTITY, o.get(CONF_OZONE_ENTITY)):
                selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
            _optional(CONF_PERENUAL_API_KEY, o.get(CONF_PERENUAL_API_KEY)):
                selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)),
            _optional(CONF_TREFLE_API_KEY, o.get(CONF_TREFLE_API_KEY)):
                selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)),
            vol.Optional(
                CONF_ENABLE_TREFLE_FALLBACK,
                default=o.get(CONF_ENABLE_TREFLE_FALLBACK, DEFAULT_ENABLE_TREFLE_FALLBACK),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_ENABLE_INATURALIST_ENRICHMENT,
                default=o.get(CONF_ENABLE_INATURALIST_ENRICHMENT, DEFAULT_ENABLE_INATURALIST_ENRICHMENT),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_UPDATE_INTERVAL,
                default=o.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=60, max=3600, step=30, unit_of_measurement="s", mode="box")
            ),
            vol.Required(
                CONF_RADIATION_SOURCE,
                default=o.get(CONF_RADIATION_SOURCE, DEFAULT_RADIATION_SOURCE),
            ): _select(RADIATION_SOURCES),
            vol.Optional(
                CONF_OUTDOOR_DATA_SOURCE,
                default=o.get(CONF_OUTDOOR_DATA_SOURCE, DEFAULT_OUTDOOR_DATA_SOURCE),
            ): _select(OUTDOOR_DATA_SOURCES),
        }
    )




# --- config flow (initial setup) ------------------------------------------

class PlantHelperConfigFlow(ConfigFlow, domain=DOMAIN):
    """Initial setup: a single hub. Plants are added from Options."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            return self.async_create_entry(
                title="Plant Helper", data={}, options=user_input
            )

        return self.async_show_form(
            step_id="user",
            data_schema=_global_schema(),
            description_placeholders={
                "info": (
                    "Set up Plant Helper. Everything here is optional and can be "
                    "changed later. Add your plants afterwards from the "
                    "integration's Configure screen."
                )
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> "PlantHelperOptionsFlow":
        return PlantHelperOptionsFlow(config_entry)


# --- options flow (lifecycle management) ----------------------------------

class PlantHelperOptionsFlow(OptionsFlow):
    """Add / edit / remove plants and edit global settings."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._entry = config_entry
        self._edit_id: str | None = None

    # -- helpers --
    def _runtime(self) -> dict[str, Any]:
        """The live per-entry runtime data (storage, learned, samples, coordinator)."""
        return self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})

    async def _load_storage(self) -> PlantStorage:
        """Return the RUNNING storage instance so mutations use one source of truth.

        Using a separate instance risks a stale copy being written back (e.g. on
        unload), which previously resurrected removed plants. Falls back to a
        fresh load only if the integration isn't currently set up.
        """
        storage = self._runtime().get("storage")
        if storage is not None:
            return storage
        storage = PlantStorage(self.hass)
        await storage.async_load()
        return storage

    def _finish(self, extra: dict[str, Any] | None = None) -> FlowResult:
        """Close the options flow and trigger exactly one reload.

        Plant data lives in storage, so a mutation wouldn't otherwise change the
        entry options (no reload). Bumping a revision nonce guarantees the
        options-update listener fires once — deterministically, and without the
        double reload a manual reload-plus-changed-options would cause.
        """
        options = {**self._entry.options}
        if extra:
            options.update(extra)
        options["_rev"] = int(self._entry.options.get("_rev", 0)) + 1
        return self.async_create_entry(title="", data=options)

    def _remove_device(self, plant_id: str) -> None:
        """Delete the plant's device (and its entities) from the registry.

        Storage removal alone leaves an orphaned device in HA; this removes it so
        deleting a plant cleans up fully, as the v3 component did.
        """
        from homeassistant.helpers import device_registry as dr

        registry = dr.async_get(self.hass)
        device = registry.async_get_device(identifiers={(DOMAIN, plant_id)})
        if device is not None:
            registry.async_remove_device(device.id)

    async def _purge_plant(self, storage: PlantStorage, plant_id: str) -> None:
        """Remove every trace of a plant: config, learned state, samples, device.

        Persisted immediately so the deletion survives the subsequent reload and
        nothing about the plant is left behind in Home Assistant.
        """
        await storage.async_remove_user_plant(plant_id)  # persists immediately

        runtime = self._runtime()
        learned = runtime.get("learned")
        if learned is not None:
            learned_remove_plant(learned.data, plant_id)
            await learned.async_save()

        samples = runtime.get("samples")
        if samples is not None:
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
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
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
    async def async_step_add_plant(self, user_input: dict[str, Any] | None = None) -> FlowResult:
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
            description_placeholders={"info": _ADD_INFO},
        )

    async def _ensure_species_stub(self, storage: PlantStorage, species: str) -> None:
        """Ensure a cache entry exists so the plant can be stored.

        No API call here: the coordinator performs the real provider lookup on its
        first cycle after setup (so the calls are real, hit the coordinator's own
        client, and show up in the API diagnostic sensors). If the species is
        already cached with real data, that data is kept.
        """
        if storage.get_plant(species) is None:
            await storage.async_add_plant(species, {"common_name": species})

    # -- edit --
    async def async_step_edit_plant_select(self, user_input: dict[str, Any] | None = None) -> FlowResult:
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

    async def async_step_edit_plant(self, user_input: dict[str, Any] | None = None) -> FlowResult:
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
                        needs_calibration = learned_swap_placement(
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
                            learned_set_timer(learned.data, self._edit_id, timer, None)
                        await learned.async_save()
                    if samples is not None:
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
            description_placeholders={"info": _EDIT_INFO},
        )

    # -- remove --
    async def async_step_remove_plant(self, user_input: dict[str, Any] | None = None) -> FlowResult:
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
            description_placeholders={"info": _REMOVE_INFO},
        )

    # -- global settings --
    async def async_step_global_settings(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            return self._finish(user_input)
        return self.async_show_form(
            step_id="global_settings",
            data_schema=_global_schema(self._entry.options),
            description_placeholders={"info": _SETTINGS_INFO},
        )


_ADD_INFO = (
    "Only the soil-moisture sensor is required. Adding soil temperature enables "
    "temperature-compensated moisture and thermal alerts; a light sensor enables "
    "indoor light adequacy and obstruction detection (outdoor plants use SMHI "
    "instead); battery (percentage or high/middle/low) pauses care when critical. "
    "Species is optional — it only fetches display context."
)
_EDIT_INFO = "Change this plant's sensors and settings. The form is pre-filled with its current configuration."
_REMOVE_INFO = "Removing a plant permanently deletes its device, entities, calibration progress, learned baselines, timers, history, and stored samples."
_SETTINGS_INFO = (
    "Global settings shared by all plants. Forecast source enables rain "
    "suppression and severe-weather alerts; the ozone sensor enables the outdoor "
    "ozone advisory. API keys are optional and only used for species context."
)
