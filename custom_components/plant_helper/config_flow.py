"""Plant Helper — configuration and options flow (v4, written from scratch).

Design goals:
  * Simple: adding a plant asks only for what the v4 engine actually uses —
    soil moisture (required), soil temperature, air humidity, light, and
    battery. Species remains optional.
  * Powerful: full lifecycle from Options — add, edit, remove plants, and edit
    global settings (credentials, Open-Meteo location overrides, ozone advisory, poll rate).
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
from homeassistant.helpers import selector

from .const import (
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_OZONE_ENTITY,
    CONF_PERENUAL_API_KEY,
    CONF_PERENUAL_ACCESS_LEVEL,
    PERENUAL_ACCESS_FREE,
    PERENUAL_ACCESS_PAID,
    CONF_TREFLE_API_KEY,
    CONF_UPDATE_INTERVAL,
    DEFAULT_PLACEMENT,
    DEFAULT_PROFILE,
    DEFAULT_RAIN_LIMIT_MM,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    PLACEMENTS,
    PROFILES,
)
from .plant_config import (
    CONF_BATTERY,
    CONF_CUSTOM_MULTIPLIER,
    CONF_LUX,
    CONF_HUMIDITY,
    CONF_MOISTURE,
    CONF_NAME,
    CONF_PLANT_ID,
    CONF_PLACEMENT,
    CONF_PROFILE,
    CONF_RAIN_LIMIT_MM,
    CONF_SOIL_TEMP,
    CONF_SPECIES,
    normalize_global_options,
)

_LOGGER = logging.getLogger(__name__)



# --- selectors ------------------------------------------------------------

def _sensor(device_classes: list[str] | None = None) -> selector.EntitySelector:
    if device_classes:
        config = selector.EntitySelectorConfig(
            domain="sensor", device_class=device_classes
        )
    else:
        config = selector.EntitySelectorConfig(domain="sensor")
    return selector.EntitySelector(config)


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
            _optional(CONF_CUSTOM_MULTIPLIER, d.get(CONF_CUSTOM_MULTIPLIER)): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0.05, max=1.0, step=0.05, mode=selector.NumberSelectorMode.BOX)
            ),
            # Sensors — moisture is required; the rest are optional but enable
            # more of the model (see step description).
            moisture_field: _sensor(["moisture", "humidity"]),
            _optional(CONF_SOIL_TEMP, d.get(CONF_SOIL_TEMP)): _sensor(["temperature"]),
            _optional(CONF_HUMIDITY, d.get(CONF_HUMIDITY)): _sensor(["humidity"]),
            _optional(CONF_LUX, d.get(CONF_LUX)): _sensor(["illuminance"]),
            _optional(CONF_BATTERY, d.get(CONF_BATTERY)): _sensor(),  # categorical ok
            vol.Optional(
                CONF_RAIN_LIMIT_MM,
                default=float(d.get(CONF_RAIN_LIMIT_MM, DEFAULT_RAIN_LIMIT_MM) or DEFAULT_RAIN_LIMIT_MM),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0.0, max=50.0, step=0.5, mode=selector.NumberSelectorMode.BOX)
            ),
        }
    )


def _global_schema() -> vol.Schema:
    """Return the Global settings schema without persisted defaults."""
    return vol.Schema(
        {
            vol.Optional(CONF_LATITUDE): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=-90, max=90, step=0.000001,
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(CONF_LONGITUDE): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=-180, max=180, step=0.000001,
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(CONF_OZONE_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Optional(CONF_PERENUAL_API_KEY): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
            ),
            vol.Optional(CONF_PERENUAL_ACCESS_LEVEL): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {"value": PERENUAL_ACCESS_FREE, "label": "Free"},
                        {"value": PERENUAL_ACCESS_PAID, "label": "Paid"},
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(CONF_TREFLE_API_KEY): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
            ),
            vol.Optional(CONF_UPDATE_INTERVAL): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=60, max=3600, step=30, unit_of_measurement="s",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
        }
    )


def _global_suggested_values(options: dict[str, Any] | None) -> dict[str, Any]:
    """Return selector-safe suggested values for Global settings."""
    return normalize_global_options(options)


# --- config flow (initial setup) ------------------------------------------

class PlantHelperConfigFlow(ConfigFlow, domain=DOMAIN):
    """Initial setup: a single hub. Plants are added from Options."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Create the single integration entry with shared Global settings."""
        if user_input is not None:
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title="Plant Helper",
                data={},
                options=normalize_global_options(user_input),
            )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                _global_schema(),
                normalize_global_options({}),
            ),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow handler."""
        from .options import PlantHelperOptionsFlow

        return PlantHelperOptionsFlow()

