"""Config flow for Plant Helper integration."""

from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
    CONF_ENABLE_INATURALIST_ENRICHMENT,
    CONF_ENABLE_TREFLE_FALLBACK,
    CONF_PERENUAL_API_KEY,
    CONF_TREFLE_API_KEY,
    CONF_UPDATE_INTERVAL,
    DEFAULT_ENABLE_INATURALIST_ENRICHMENT,
    DEFAULT_ENABLE_TREFLE_FALLBACK,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    EVENT_PLANT_DATA_FETCHED,
    EVENT_USER_PLANT_ADDED,
    EVENT_USER_PLANT_REMOVED,
    EVENT_DATABASE_RESET,
)
from .helpers import (
    extract_common_name as _extract_common_name,
    extract_species_key as _extract_species_key,
)

_LOGGER = logging.getLogger(__name__)

CONF_MENU_ACTION = "menu_action"
CONF_COMMON_NAME_SEARCH = "common_name_search"
CONF_SELECTED_SPECIES = "selected_species"
CONF_CUSTOM_NAME = "custom_name"
CONF_PLANT_ID = "plant_id"
CONF_FORCE_FETCH = "force_fetch"
CONF_CONFIRM_RESET = "confirm_reset"
CONF_SOIL_TEMPERATURE_ENTITY = "soil_temperature_entity"
CONF_SOIL_HUMIDITY_ENTITY = "soil_humidity_entity"
CONF_ROOM_TEMPERATURE_ENTITY = "room_temperature_entity"
CONF_ROOM_HUMIDITY_ENTITY = "room_humidity_entity"
CONF_ROOM_LUX_ENTITY = "room_lux_entity"

ENTITY_FIELDS = (
    CONF_SOIL_TEMPERATURE_ENTITY,
    CONF_SOIL_HUMIDITY_ENTITY,
    CONF_ROOM_TEMPERATURE_ENTITY,
    CONF_ROOM_HUMIDITY_ENTITY,
    CONF_ROOM_LUX_ENTITY,
)

ACTION_ADD_CONFIGURED_PLANT = "add_configured_plant"
ACTION_REMOVE_CONFIGURED_PLANT = "remove_configured_plant"
ACTION_FETCH_SPECIES = "fetch_species"
ACTION_VIEW_PLANTS = "view_plants"
ACTION_RESET_DATABASE = "reset_database"
ACTION_SETTINGS = "settings"

SETUP_INFO = """Welcome to Plant Helper!

Monitor and care for your plants by combining real sensor data with plant care knowledge from online databases.

REQUIRED: Perenual API key
Get a free key: https://perenual.com/docs/api
Free tier: 100 requests/day

OPTIONAL: Trefle API token
Backup plant database: https://trefle.io/

Optional enhancements:
- iNaturalist enrichment: Extra photos and details (no API key needed)
- Trefle fallback: Search Trefle when Perenual comes up empty

Update interval: How often sensors refresh (default: 300 seconds)
Source sensors trigger immediate updates regardless of this setting."""

MENU_INFO = """Plant Helper Options

Add Configured Plant
Create a new plant device with sensors. Searches for plant data and lets you link your temperature, humidity, light, and moisture sensors.

Remove Configured Plant
Delete a plant device and all its sensors from Home Assistant.

Fetch Species to Cache
Download plant care data to your local database without creating sensors. Useful for building your plant library.

View Plants
See what you have: Plants you're monitoring (with sensors) and plant species you've downloaded (available to use).

Reset Plant Database
Clear all cached plant data and configured plants. Your API keys and settings are not affected.

Integration Settings
Change API keys, enable/disable features, and adjust update interval."""

ADD_SEARCH_INFO = """Search for your plant by its common name

Examples: "Snake Plant", "Monstera", "Pothos", "Peace Lily"

Plant Helper will search in this order:
1. Your local cache (instant, no API calls)
2. Perenual database
3. Trefle database (if enabled)

What happens next:
- If found: Plant data is saved to your local cache
- Next step: You'll link your sensors and create the plant device

Note: This step only searches for plant species information. The actual sensors are created in the next step."""

ADD_DETAILS_INFO = """Plant found! Now let's create your plant sensors.

Sensors that will be created:
- Plant Status: Overall health and current state
- Calculated Soil Moisture: Smart watering model
- Light Score: Daily light accumulation
- Temperature Stress: Time outside safe range
- Health Score: Overall wellness (0-100)
- Care Action: Next recommended action

Source sensors to connect (all optional):

Soil temperature
- For more accurate soil moisture modeling
- Optional - most people don't have this

Soil moisture
- Your physical moisture sensor
- If skipped, Plant Helper calculates it for you using watering events + evaporation

Room temperature (RECOMMENDED)
- For temperature stress and health calculations

Room humidity (RECOMMENDED)
- For humidity suitability and drying speed

Room light in lux (RECOMMENDED)
- For daily light tracking and growth mode

TIP: Even with zero source sensors, Plant Helper can track watering and provide care recommendations!"""

FETCH_INFO = """Pre-fetch plant data without creating sensors

This downloads and caches plant care information to your local database without creating any Home Assistant sensors or devices. Use "Add Configured Plant" afterwards to actually create sensors.

Useful when you want to:
- Explore what plant data is available
- Build your local cache for offline use
- Prepare data before setting up sensors

Force fetch option:
- Normal: Uses cached data if available (fast, no API calls)
- Force fetch: Always gets fresh data from online providers (uses API quota)"""

SETTINGS_INFO = """Configure how Plant Helper works

Perenual API key (REQUIRED)
Primary plant database. Free tier: 100 requests/day
Get a key: https://perenual.com/docs/api

Trefle API token (OPTIONAL)
Backup database for plants Perenual doesn't have
Get a token: https://trefle.io/

Enable Trefle fallback
Automatically search Trefle when Perenual comes up empty

iNaturalist enrichment (OPTIONAL)
Adds extra photos and details after plant identification
No API key needed

Update interval (seconds)
How often Plant Helper recalculates sensors (default: 300)
Source sensors still trigger immediate updates"""

REMOVE_INFO = """Remove a configured plant

This deletes the plant device and all its sensors from Home Assistant. The cached species data stays in your local database, so you can re-add the same plant later without searching again."""


def _slugify(value: str) -> str:
    """Slugify a plant id."""
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9_]+", "_", value)
    value = re.sub(r"_+", "_", value)
    return value.strip("_") or "plant"


def _normalize(value: Any) -> str:
    """Normalize text."""
    value = str(value or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _common_name_candidates(plant_data: dict[str, Any]) -> list[str]:
    """Return common-name candidates."""
    candidates: list[str] = []
    for key in ("common_name", "commonName", "common", "other_name", "otherName"):
        value = plant_data.get(key)
        if isinstance(value, str) and value.strip():
            candidates.append(value.strip())
        elif isinstance(value, list):
            candidates.extend(
                item.strip()
                for item in value
                if isinstance(item, str) and item.strip()
            )
    return list(dict.fromkeys(candidates))


def _common_name_matches(search_text: str, plant_data: dict[str, Any]) -> bool:
    """Return true if plant matches search by common name."""
    search = _normalize(search_text)
    if not search:
        return False
    tokens = set(search.split())
    for candidate in _common_name_candidates(plant_data):
        norm = _normalize(candidate)
        if search in norm or norm in search:
            return True
        if tokens and tokens.issubset(set(norm.split())):
            return True
    return False


def _display_name(plant_data: dict[str, Any], fallback: str) -> str:
    """Return display name."""
    names = _common_name_candidates(plant_data)
    return names[0] if names else fallback


def _entry_value(entry: config_entries.ConfigEntry, key: str, default: Any) -> Any:
    """Return options value, then data value, then default."""
    value = entry.options.get(key, None)
    if value is None:
        value = entry.data.get(key, None)
    return default if value is None else value


def _source_entities_from_input(user_input: dict[str, Any]) -> dict[str, str]:
    """Build source entity mapping with proper soil/room prefixes."""
    entities = {}
    
    # Save with clean keys (no _entity suffix)
    if user_input.get(CONF_SOIL_TEMPERATURE_ENTITY):
        entities["soil_temperature"] = user_input[CONF_SOIL_TEMPERATURE_ENTITY]
    
    if user_input.get(CONF_SOIL_HUMIDITY_ENTITY):
        entities["soil_moisture"] = user_input[CONF_SOIL_HUMIDITY_ENTITY]
    
    if user_input.get(CONF_ROOM_TEMPERATURE_ENTITY):
        entities["room_temperature"] = user_input[CONF_ROOM_TEMPERATURE_ENTITY]
    
    if user_input.get(CONF_ROOM_HUMIDITY_ENTITY):
        entities["room_humidity"] = user_input[CONF_ROOM_HUMIDITY_ENTITY]
    
    if user_input.get(CONF_ROOM_LUX_ENTITY):
        entities["room_lux"] = user_input[CONF_ROOM_LUX_ENTITY]
    
    return entities


def _format_linked_sources(entities: dict[str, str]) -> str:
    """Return a friendly linked source sensor summary."""
    rows = (
        ("Soil temperature", entities.get("soil_temperature")),
        ("Soil moisture", entities.get("soil_moisture")),
        ("Room temperature", entities.get("room_temperature")),
        ("Room humidity", entities.get("room_humidity")),
        ("Room light", entities.get("room_lux")),
    )
    return "\n".join(f"- {label}: {entity_id or 'not set'}" for label, entity_id in rows)


def _settings_schema(
    *,
    api_key: str = "",
    trefle_key: str = "",
    update_interval: int = DEFAULT_UPDATE_INTERVAL,
    enable_trefle: bool = DEFAULT_ENABLE_TREFLE_FALLBACK,
    enable_inat: bool = DEFAULT_ENABLE_INATURALIST_ENRICHMENT,
) -> vol.Schema:
    """Return integration settings schema."""
    return vol.Schema(
        {
            vol.Optional(CONF_PERENUAL_API_KEY, default=api_key): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
            ),
            vol.Optional(CONF_TREFLE_API_KEY, default=trefle_key): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
            ),
            vol.Optional(CONF_ENABLE_TREFLE_FALLBACK, default=enable_trefle): selector.BooleanSelector(),
            vol.Optional(CONF_ENABLE_INATURALIST_ENRICHMENT, default=enable_inat): selector.BooleanSelector(),
            vol.Optional(CONF_UPDATE_INTERVAL, default=update_interval): vol.All(
                vol.Coerce(int),
                vol.Range(min=60, max=86400),
            ),
        }
    )


def _sensor_entity_selector() -> selector.EntitySelector:
    """Return a sensor-only entity selector."""
    return selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor"))


def _menu_schema(configured_count: int, cached_count: int) -> vol.Schema:
    """Return options menu schema."""
    return vol.Schema(
        {
            vol.Required(CONF_MENU_ACTION): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {
                            "value": ACTION_ADD_CONFIGURED_PLANT,
                            "label": f"Add Configured Plant ({configured_count} configured)",
                        },
                        {
                            "value": ACTION_REMOVE_CONFIGURED_PLANT,
                            "label": "Remove Configured Plant",
                        },
                        {
                            "value": ACTION_FETCH_SPECIES,
                            "label": f"Fetch Species to Cache ({cached_count} cached)",
                        },
                        {
                            "value": ACTION_VIEW_PLANTS,
                            "label": "View Configured and Cached Plants",
                        },
                        {
                            "value": ACTION_RESET_DATABASE,
                            "label": "Reset Plant Database",
                        },
                        {
                            "value": ACTION_SETTINGS,
                            "label": "Integration Settings",
                        },
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
        }
    )


def _search_schema() -> vol.Schema:
    """Return plant search schema."""
    return vol.Schema(
        {
            vol.Required(CONF_COMMON_NAME_SEARCH): selector.TextSelector(
                selector.TextSelectorConfig()
            )
        }
    )


def _fetch_schema() -> vol.Schema:
    """Return fetch species schema."""
    return vol.Schema(
        {
            vol.Required(CONF_COMMON_NAME_SEARCH): selector.TextSelector(
                selector.TextSelectorConfig()
            ),
            vol.Optional(CONF_FORCE_FETCH, default=False): selector.BooleanSelector(),
        }
    )


def _reset_schema() -> vol.Schema:
    """Return reset confirmation schema."""
    return vol.Schema(
        {
            vol.Required(CONF_CONFIRM_RESET, default=False): selector.BooleanSelector(),
        }
    )


def _add_schema(
    matches: list[dict[str, str]],
    *,
    default_custom_name: str,
    default_plant_id: str,
) -> vol.Schema:
    """Return add configured plant schema."""
    return vol.Schema(
        {
            vol.Required(CONF_SELECTED_SPECIES): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {"value": item["species"], "label": item["common_name"]}
                        for item in matches
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(CONF_CUSTOM_NAME, default=default_custom_name): selector.TextSelector(
                selector.TextSelectorConfig()
            ),
            vol.Optional(CONF_PLANT_ID, default=default_plant_id): selector.TextSelector(
                selector.TextSelectorConfig()
            ),
            vol.Optional(CONF_SOIL_TEMPERATURE_ENTITY): _sensor_entity_selector(),
            vol.Optional(CONF_SOIL_HUMIDITY_ENTITY): _sensor_entity_selector(),
            vol.Optional(CONF_ROOM_TEMPERATURE_ENTITY): _sensor_entity_selector(),
            vol.Optional(CONF_ROOM_HUMIDITY_ENTITY): _sensor_entity_selector(),
            vol.Optional(CONF_ROOM_LUX_ENTITY): _sensor_entity_selector(),
        }
    )


def _remove_schema(user_plants: dict[str, Any]) -> vol.Schema:
    """Return remove configured plant schema."""
    return vol.Schema(
        {
            vol.Required(CONF_PLANT_ID): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {"value": plant_id, "label": data.get("custom_name") or plant_id}
                        for plant_id, data in sorted(user_plants.items())
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
        }
    )


class PlantHelperConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle Plant Helper config flow."""

    VERSION = 1

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Initial setup."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            return self.async_create_entry(title="Plant Helper", data=dict(user_input))

        return self.async_show_form(
            step_id="user",
            data_schema=_settings_schema(),
            errors={},
            description_placeholders={"info": SETTINGS_INFO},
        )

    async def async_step_reconfigure(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Reconfigure existing entry."""
        entry = self._get_reconfigure_entry()

        if user_input is not None:
            return self.async_update_reload_and_abort(entry, data={**entry.data, **user_input})

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_settings_schema(
                api_key=_entry_value(entry, CONF_PERENUAL_API_KEY, ""),
                trefle_key=_entry_value(entry, CONF_TREFLE_API_KEY, ""),
                update_interval=_entry_value(entry, CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
                enable_trefle=_entry_value(entry, CONF_ENABLE_TREFLE_FALLBACK, DEFAULT_ENABLE_TREFLE_FALLBACK),
                enable_inat=_entry_value(entry, CONF_ENABLE_INATURALIST_ENRICHMENT, DEFAULT_ENABLE_INATURALIST_ENRICHMENT),
            ),
            errors={},
            description_placeholders={"info": SETTINGS_INFO},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        """Create options flow."""
        return PlantHelperOptionsFlow()


class PlantHelperOptionsFlow(config_entries.OptionsFlow):
    """Handle Plant Helper options flow."""

    def __init__(self) -> None:
        """Initialize options flow."""
        self._matches: list[dict[str, str]] = []
        self._result_info = "No result."
        self._lookup_info = "No lookup has been performed."

    def _data(self) -> dict[str, Any]:
        """Return runtime data."""
        data = self.hass.data.get(DOMAIN, {})
        entry_data = data.get(self.config_entry.entry_id)
        return entry_data if isinstance(entry_data, dict) else data

    def _storage(self) -> Any | None:
        """Return storage."""
        return self._data().get("storage")

    def _api(self) -> Any | None:
        """Return API client."""
        return self._data().get("api")

    def _counts(self) -> tuple[int, int]:
        """Return configured plant and cached species counts."""
        storage = self._storage()
        if not storage:
            return (0, 0)
        return (len(storage.get_all_user_plants()), len(storage.get_all_plants()))

    def _search_cached(self, text: str) -> list[dict[str, str]]:
        """Search cached plants."""
        storage = self._storage()
        if not storage:
            return []

        found: list[dict[str, str]] = []
        for species, plant_data in storage.get_all_plants().items():
            if _common_name_matches(text, plant_data):
                found.append(
                    {
                        "species": species,
                        "common_name": _display_name(plant_data, species),
                    }
                )
        return sorted(found, key=lambda item: item["common_name"].lower())

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Options menu."""
        configured_count, cached_count = self._counts()

        if user_input is not None:
            action = user_input.get(CONF_MENU_ACTION)
            if action == ACTION_ADD_CONFIGURED_PLANT:
                return await self.async_step_add_plant_search()
            if action == ACTION_REMOVE_CONFIGURED_PLANT:
                return await self.async_step_remove_plant()
            if action == ACTION_FETCH_SPECIES:
                return await self.async_step_fetch_species()
            if action == ACTION_VIEW_PLANTS:
                return await self.async_step_view_plants()
            if action == ACTION_RESET_DATABASE:
                return await self.async_step_reset_database()
            if action == ACTION_SETTINGS:
                return await self.async_step_settings()

        return self.async_show_form(
            step_id="init",
            data_schema=_menu_schema(configured_count, cached_count),
            errors={},
            description_placeholders={"info": MENU_INFO},
        )

    async def async_step_add_plant_search(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Search and begin configured plant setup."""
        if user_input is not None:
            text = user_input.get(CONF_COMMON_NAME_SEARCH, "").strip()
            if not text:
                return self.async_show_form(
                    step_id="add_plant_search",
                    data_schema=_search_schema(),
                    errors={CONF_COMMON_NAME_SEARCH: "required"},
                    description_placeholders={"info": ADD_SEARCH_INFO},
                )

            self._matches = self._search_cached(text)
            if self._matches:
                self._lookup_info = (
                    "Path used: Local database cache hit\n"
                    "API checked: No\n"
                    "API call made: No"
                )
                return await self.async_step_add_plant_details()

            storage = self._storage()
            api = self._api()
            if not storage or not api:
                self._result_info = (
                    "Add Configured Plant failed.\n\n"
                    f"Search: {text}\n"
                    "Result: Storage or API client is not loaded."
                )
                return await self.async_step_result()

            result = await api.fetch_plant(text)
            if result.found and result.data:
                species = _extract_species_key(result.data, text)
                result.data.setdefault("species", species)
                result.data.setdefault("common_name", _extract_common_name(result.data, text))
                await storage.async_add_plant(species, result.data)
                await self._refresh()

                self.hass.bus.async_fire(
                    EVENT_PLANT_DATA_FETCHED,
                    {
                        "entry_id": self.config_entry.entry_id,
                        "species": species,
                        "common_name": result.data.get("common_name"),
                        "provider": result.provider,
                    },
                )

                self._lookup_info = (
                    "Path used: Local DB miss -> provider chain\n"
                    f"Provider: {result.provider}\n"
                    "API checked: Yes\n"
                    f"API call made: {result.api_called}"
                )
                self._matches = self._search_cached(text) or [
                    {
                        "species": species,
                        "common_name": result.data.get("common_name") or species,
                    }
                ]
                return await self.async_step_add_plant_details()

            self._result_info = (
                "Add Configured Plant failed.\n\n"
                f"Search: {text}\n"
                f"Result: {result.message}"
            )
            return await self.async_step_result()

        return self.async_show_form(
            step_id="add_plant_search",
            data_schema=_search_schema(),
            errors={},
            description_placeholders={"info": ADD_SEARCH_INFO},
        )

    async def async_step_add_plant_details(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Add configured plant details."""
        storage = self._storage()
        if not storage:
            self._result_info = "Add Configured Plant failed. Storage is not loaded."
            return await self.async_step_result()
        if not self._matches:
            return await self.async_step_add_plant_search()

        errors: dict[str, str] = {}
        if user_input is not None:
            selected = user_input.get(CONF_SELECTED_SPECIES)
            match = next((item for item in self._matches if item["species"] == selected), None)
            if not match:
                self._result_info = "Add Configured Plant failed. Invalid plant selection."
                return await self.async_step_result()

            custom_name = user_input.get(CONF_CUSTOM_NAME, "").strip() or match["common_name"]
            plant_id = user_input.get(CONF_PLANT_ID, "").strip() or _slugify(custom_name)

            if plant_id in storage.get_all_user_plants():
                errors[CONF_PLANT_ID] = "plant_id_exists"
            else:
                entities = _source_entities_from_input(user_input)
                added = await storage.async_add_user_plant(
                    plant_id=plant_id,
                    species=selected,
                    custom_name=custom_name,
                    entities=entities,
                )
                if added:
                    await self._refresh()
                    self.hass.bus.async_fire(
                        EVENT_USER_PLANT_ADDED,
                        {
                            "entry_id": self.config_entry.entry_id,
                            "plant_id": plant_id,
                            "species": selected,
                            "custom_name": custom_name,
                            "entities": entities,
                        },
                    )
                    self._result_info = (
                        "Configured plant added successfully.\n\n"
                        f"{self._lookup_info}\n\n"
                        f"Name: {custom_name}\n"
                        f"Plant ID: {plant_id}\n"
                        f"Cached species key: {selected}\n\n"
                        "Created sensors:\n"
                        "- Plant Status\n"
                        "- Calculated Soil Moisture\n"
                        "- Light Score\n"
                        "- Temperature Stress Load\n"
                        "- Health Score\n"
                        "- Care Action\n\n"
                        "Linked source sensors:\n"
                        f"{_format_linked_sources(entities)}"
                    )
                    return await self.async_step_result()

                self._result_info = (
                    "Add Configured Plant failed.\n\n"
                    f"Plant ID: {plant_id}\n"
                    f"Cached species key: {selected}\n\n"
                    "The species was not found in the local database."
                )
                return await self.async_step_result()

        default_name = self._matches[0]["common_name"]
        return self.async_show_form(
            step_id="add_plant_details",
            data_schema=_add_schema(
                self._matches,
                default_custom_name=default_name,
                default_plant_id=_slugify(default_name),
            ),
            errors=errors,
            description_placeholders={"info": ADD_DETAILS_INFO},
        )

    async def async_step_fetch_species(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Fetch species into local DB."""
        if user_input is not None:
            text = user_input.get(CONF_COMMON_NAME_SEARCH, "").strip()
            force_fetch = user_input.get(CONF_FORCE_FETCH, False)
            storage = self._storage()
            api = self._api()

            if not text:
                return self.async_show_form(
                    step_id="fetch_species",
                    data_schema=_fetch_schema(),
                    errors={CONF_COMMON_NAME_SEARCH: "required"},
                    description_placeholders={"info": FETCH_INFO},
                )
            if not storage or not api:
                self._result_info = "Fetch Species to Cache failed. Storage or API client is not loaded."
                return await self.async_step_result()

            if not force_fetch:
                matches = self._search_cached(text)
                if matches:
                    self._result_info = (
                        "Species already exists in local cache.\n\n"
                        "Path used: Local database cache hit\n"
                        "API checked: No\n"
                        "API call made: No\n"
                        f"Matches: {len(matches)}"
                    )
                    return await self.async_step_result()

            result = await api.fetch_plant(text, force_fetch=force_fetch)
            if result.found and result.data:
                species = _extract_species_key(result.data, text)
                result.data.setdefault("species", species)
                result.data.setdefault("common_name", _extract_common_name(result.data, text))
                await storage.async_add_plant(species, result.data)
                await self._refresh()
                self.hass.bus.async_fire(
                    EVENT_PLANT_DATA_FETCHED,
                    {
                        "entry_id": self.config_entry.entry_id,
                        "species": species,
                        "common_name": result.data.get("common_name"),
                        "provider": result.provider,
                        "force_fetch": force_fetch,
                    },
                )
                self._result_info = (
                    "Species cached successfully.\n\n"
                    f"Provider: {result.provider}\n"
                    f"API checked: {result.api_checked}\n"
                    f"API call made: {result.api_called}\n"
                    f"Common name: {result.data.get('common_name')}\n"
                    f"Cached species key: {species}\n"
                    f"Force fetch: {force_fetch}\n\n"
                    "This only caches species data. Use Add Configured Plant to create plant sensors."
                )
            else:
                self._result_info = (
                    "Fetch Species to Cache failed.\n\n"
                    f"Search: {text}\n"
                    f"Result: {result.message}"
                )
            return await self.async_step_result()

        return self.async_show_form(
            step_id="fetch_species",
            data_schema=_fetch_schema(),
            errors={},
            description_placeholders={"info": FETCH_INFO},
        )

    async def async_step_remove_plant(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Remove configured plant."""
        storage = self._storage()
        plants = storage.get_all_user_plants() if storage else {}
        if user_input is not None and storage:
            plant_id = user_input.get(CONF_PLANT_ID)
            if await storage.async_remove_user_plant(plant_id):
                await self._refresh()
                self.hass.bus.async_fire(
                    EVENT_USER_PLANT_REMOVED,
                    {"entry_id": self.config_entry.entry_id, "plant_id": plant_id},
                )
                self._result_info = (
                    "Configured plant removed successfully.\n\n"
                    f"Plant ID: {plant_id}"
                )
                return await self.async_step_result()

        if not plants:
            self._result_info = "No configured plants found."
            return await self.async_step_result()

        return self.async_show_form(
            step_id="remove_plant",
            data_schema=_remove_schema(plants),
            errors={},
            description_placeholders={"info": REMOVE_INFO},
        )

    async def async_step_view_plants(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """View configured and cached plants."""
        if user_input is not None:
            return await self.async_step_init()

        storage = self._storage()
        if not storage:
            info = "Storage is not loaded."
        else:
            user_plants = storage.get_all_user_plants()
            cached_plants = storage.get_all_plants()
            configured_lines = [
                f"- {data.get('custom_name') or plant_id} ({plant_id})"
                for plant_id, data in sorted(user_plants.items())
            ] or ["- None"]
            cached_lines = [
                f"- {_display_name(data, species)}"
                for species, data in sorted(
                    cached_plants.items(),
                    key=lambda item: _display_name(item[1], item[0]).lower(),
                )
            ] or ["- None"]
            info = (
                f"Configured plants: {len(user_plants)}\n"
                f"Cached species: {len(cached_plants)}\n\n"
                "Configured plants\n"
                + "\n".join(configured_lines)
                + "\n\nCached common names\n"
                + "\n".join(cached_lines)
            )

        return self.async_show_form(
            step_id="view_plants",
            data_schema=vol.Schema({}),
            errors={},
            description_placeholders={"info": info},
        )

    async def async_step_reset_database(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Reset local DB."""
        storage = self._storage()
        if not storage:
            self._result_info = "Reset failed. Storage is not loaded."
            return await self.async_step_result()

        if user_input is not None and user_input.get(CONF_CONFIRM_RESET):
            result = await storage.async_clear_database(clear_user_plants=True)
            await self._refresh()
            self.hass.bus.async_fire(
                EVENT_DATABASE_RESET,
                {"entry_id": self.config_entry.entry_id, **result, "clear_user_plants": True},
            )
            self._result_info = (
                "Plant database reset successfully.\n\n"
                f"Removed cached species: {result.get('removed_cached_species', 0)}\n"
                f"Removed configured plants: {result.get('removed_configured_plants', 0)}"
            )
            return await self.async_step_result()

        info = (
            "Reset Plant Database\n\n"
            f"This will remove {len(storage.get_all_plants())} cached species and "
            f"{len(storage.get_all_user_plants())} configured plants.\n"
            "Integration settings and API keys are not removed."
        )
        return self.async_show_form(
            step_id="reset_database",
            data_schema=_reset_schema(),
            errors={},
            description_placeholders={"info": info},
        )

    async def async_step_settings(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Integration settings."""
        entry = self.config_entry
        if user_input is not None:
            return self.async_create_entry(title="", data={**entry.options, **user_input})

        return self.async_show_form(
            step_id="settings",
            data_schema=_settings_schema(
                api_key=_entry_value(entry, CONF_PERENUAL_API_KEY, ""),
                trefle_key=_entry_value(entry, CONF_TREFLE_API_KEY, ""),
                update_interval=_entry_value(entry, CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
                enable_trefle=_entry_value(entry, CONF_ENABLE_TREFLE_FALLBACK, DEFAULT_ENABLE_TREFLE_FALLBACK),
                enable_inat=_entry_value(entry, CONF_ENABLE_INATURALIST_ENRICHMENT, DEFAULT_ENABLE_INATURALIST_ENRICHMENT),
            ),
            errors={},
            description_placeholders={"info": SETTINGS_INFO},
        )

    async def async_step_result(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Show result."""
        if user_input is not None:
            return await self.async_step_init()
        return self.async_show_form(
            step_id="result",
            data_schema=vol.Schema({}),
            errors={},
            description_placeholders={"info": self._result_info},
        )

    async def _refresh(self) -> None:
        """Refresh coordinator."""
        coordinator = self._data().get("coordinator")
        if coordinator:
            try:
                await coordinator.async_request_refresh()
            except Exception:
                _LOGGER.exception("Failed to refresh Plant Helper coordinator")
