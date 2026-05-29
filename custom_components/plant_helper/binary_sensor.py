"""Binary sensor platform for Plant Helper integration.

Monitors:
- Plant Helper API connectivity and provider status
- Plant water/light/temperature issues
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, Event, callback
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    PERENUAL_DAILY_LIMIT,
    TREFLE_DAILY_LIMIT,
    INATURALIST_DAILY_LIMIT,
    EVENT_USER_PLANT_ADDED,
    EVENT_USER_PLANT_REMOVED,
    EVENT_DATABASE_RESET,
    EVENT_PLANT_DATA_FETCHED,
    EVENT_PLANT_WATERED,
    EVENT_PLANT_FERTILIZED,
    EVENT_PLANT_INSPECTED,
)
from .helpers import get_linked_entity as _get_linked_entity
from .plant_care_algorithms import PlantCareAlgorithms

_LOGGER = logging.getLogger(__name__)

# Recompute time-dependent metrics on this cadence even when no linked source
# sensor has changed (mirrors the sensor platform).
METRIC_REFRESH_INTERVAL = timedelta(minutes=5)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Plant Helper binary sensors from config entry."""
    runtime_data = hass.data[DOMAIN][entry.entry_id]
    storage = runtime_data["storage"]
    api = runtime_data.get("api")
    coordinator = runtime_data.get("coordinator")
    
    # Reuse the shared algorithms instance from sensor platform (or create if not yet ready)
    algorithms = runtime_data.get("algorithms")
    if algorithms is None:
        algorithms = PlantCareAlgorithms(hass, storage)
        runtime_data["algorithms"] = algorithms

    # Track plant binary sensors for dynamic add/remove
    plant_entities: dict[str, list[BinarySensorEntity]] = {}

    entities: list[BinarySensorEntity] = [
        PlantHelperAPIConnectivityBinarySensor(
            hass=hass,
            entry=entry,
            api=api,
            coordinator=coordinator,
        )
    ]

    user_plants = storage.get_all_user_plants()

    for plant_id, plant_data in user_plants.items():
        species = plant_data.get("species")
        plant_info = storage.get_plant(species)

        if not plant_info:
            _LOGGER.warning(
                "Species '%s' not found for configured plant '%s'",
                species,
                plant_id,
            )
            continue

        plant_binary_sensors = [
            PlantNeedsWaterSensor(
                hass=hass,
                entry=entry,
                plant_id=plant_id,
                plant_data=plant_data,
                plant_info=plant_info,
                storage=storage,
                algorithms=algorithms,
            ),
            PlantLowLightSensor(
                hass=hass,
                entry=entry,
                plant_id=plant_id,
                plant_data=plant_data,
                plant_info=plant_info,
                storage=storage,
                algorithms=algorithms,
            ),
            PlantTemperatureIssueSensor(
                hass=hass,
                entry=entry,
                plant_id=plant_id,
                plant_data=plant_data,
                plant_info=plant_info,
                storage=storage,
                algorithms=algorithms,
            ),
        ]
        
        entities.extend(plant_binary_sensors)
        plant_entities[plant_id] = plant_binary_sensors

    async_add_entities(entities, True)

    # Handle dynamic plant addition
    async def _handle_plant_added(event: Event) -> None:
        if event.data.get("entry_id") not in (None, entry.entry_id):
            return

        plant_id = event.data.get("plant_id")
        if not plant_id or plant_id in plant_entities:
            return

        plant_data = storage.get_user_plant(plant_id)
        if not plant_data:
            return

        species = plant_data.get("species")
        plant_info = storage.get_plant(species)

        if not plant_info:
            _LOGGER.warning(
                "Species '%s' not found for configured plant '%s'",
                species,
                plant_id,
            )
            return

        suite = [
            PlantNeedsWaterSensor(
                hass=hass,
                entry=entry,
                plant_id=plant_id,
                plant_data=plant_data,
                plant_info=plant_info,
                storage=storage,
                algorithms=algorithms,
            ),
            PlantLowLightSensor(
                hass=hass,
                entry=entry,
                plant_id=plant_id,
                plant_data=plant_data,
                plant_info=plant_info,
                storage=storage,
                algorithms=algorithms,
            ),
            PlantTemperatureIssueSensor(
                hass=hass,
                entry=entry,
                plant_id=plant_id,
                plant_data=plant_data,
                plant_info=plant_info,
                storage=storage,
                algorithms=algorithms,
            ),
        ]

        plant_entities[plant_id] = suite
        async_add_entities(suite, True)

    # Handle dynamic plant removal
    async def _handle_plant_removed(event: Event) -> None:
        if event.data.get("entry_id") not in (None, entry.entry_id):
            return

        plant_id = event.data.get("plant_id")
        if not plant_id:
            return

        for entity in plant_entities.pop(plant_id, []):
            try:
                await entity.async_remove()
            except Exception:
                _LOGGER.debug("Failed removing binary sensor for plant %s", plant_id)

    # Handle database reset
    async def _handle_database_reset(event: Event) -> None:
        if event.data.get("entry_id") not in (None, entry.entry_id):
            return

        for plant_id in list(plant_entities):
            for entity in plant_entities.pop(plant_id, []):
                try:
                    await entity.async_remove()
                except Exception:
                    _LOGGER.debug("Failed removing binary sensor for plant %s", plant_id)

    # Register event listeners
    entry.async_on_unload(
        hass.bus.async_listen(EVENT_USER_PLANT_ADDED, _handle_plant_added)
    )
    entry.async_on_unload(
        hass.bus.async_listen(EVENT_USER_PLANT_REMOVED, _handle_plant_removed)
    )
    entry.async_on_unload(
        hass.bus.async_listen(EVENT_DATABASE_RESET, _handle_database_reset)
    )
    _LOGGER.info("Created %d Plant Helper binary sensors", len(entities))


def _safe_float(value: Any) -> float | None:
    """Convert value to float safely."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class PlantHelperBinaryBase(BinarySensorEntity):
    """Base binary sensor for Plant Helper."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
    ) -> None:
        """Initialize base binary sensor."""
        self.hass = hass
        self._entry = entry

    @property
    def device_info(self) -> DeviceInfo:
        """Return integration device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Plant Helper",
            manufacturer="Plant Helper",
            model="Plant Helper",
        )


class PlantHelperAPIConnectivityBinarySensor(PlantHelperBinaryBase):
    """Monitor Plant Helper API connectivity.

    Binary sensor is ON when the API layer is usable:
    - API orchestrator exists
    - Perenual provider has a key
    - Perenual daily limit is not reached
    - no current fatal provider error is recorded

    Binary sensor is OFF when there is an API problem.
    """

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: Any | None,
        coordinator: Any | None,
    ) -> None:
        """Initialize API connectivity sensor."""
        super().__init__(hass, entry)
        self._api = api
        self._coordinator = coordinator
        self._attr_name = "Plant Helper API Connectivity"
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_api_connectivity"
        self._attr_icon = "mdi:api"

    async def async_added_to_hass(self) -> None:
        """Start periodic update tracking."""
        await super().async_added_to_hass()

        self.async_on_remove(
            async_track_time_interval(
                self.hass,
                self._handle_time_update,
                timedelta(minutes=5),
            )
        )

    @callback
    def _handle_time_update(self, now) -> None:
        """Update state on interval."""
        self.async_schedule_update_ha_state(True)

    def _get_api_status(self) -> dict[str, Any]:
        """Check availability status of all APIs.
        
        Returns dict with availability status for each provider and aggregate status.
        """
        if self._api is None:
            return {
                "perenual_available": False,
                "trefle_available": False,
                "inaturalist_available": False,
                "any_available": False,
                "perenual_at_limit": False,
                "trefle_at_limit": False,
                "inaturalist_at_limit": False,
            }

        # Check Perenual status
        perenual_key = getattr(self._api, "perenual_key", None)
        perenual_provider = getattr(self._api, "perenual", None)
        perenual_calls = 0
        if perenual_provider is not None:
            limiter = getattr(perenual_provider, "limiter", None)
            if limiter is not None:
                if hasattr(limiter, "reset_if_needed"):
                    limiter.reset_if_needed()
                perenual_calls = int(getattr(limiter, "calls_today", 0))
        
        perenual_at_limit = perenual_calls >= PERENUAL_DAILY_LIMIT
        perenual_available = bool(perenual_key) and not perenual_at_limit

        # Check Trefle status
        enable_trefle = bool(getattr(self._api, "enable_trefle_fallback", False))
        trefle_key = getattr(self._api, "trefle_key", None)
        trefle_provider = getattr(self._api, "trefle", None)
        trefle_calls = 0
        if trefle_provider is not None:
            limiter = getattr(trefle_provider, "limiter", None)
            if limiter is not None:
                if hasattr(limiter, "reset_if_needed"):
                    limiter.reset_if_needed()
                trefle_calls = int(getattr(limiter, "calls_today", 0))
        
        trefle_at_limit = trefle_calls >= TREFLE_DAILY_LIMIT
        trefle_available = enable_trefle and bool(trefle_key) and not trefle_at_limit

        # Check iNaturalist status
        enable_inaturalist = bool(getattr(self._api, "enable_inaturalist_enrichment", False))
        inaturalist_provider = getattr(self._api, "inaturalist", None)
        inaturalist_calls = 0
        if inaturalist_provider is not None:
            limiter = getattr(inaturalist_provider, "limiter", None)
            if limiter is not None:
                if hasattr(limiter, "reset_if_needed"):
                    limiter.reset_if_needed()
                inaturalist_calls = int(getattr(limiter, "calls_today", 0))
        
        inaturalist_at_limit = inaturalist_calls >= INATURALIST_DAILY_LIMIT
        inaturalist_available = enable_inaturalist and not inaturalist_at_limit

        # At least one primary provider (Perenual or Trefle) must be available
        any_available = perenual_available or trefle_available

        return {
            "perenual_available": perenual_available,
            "trefle_available": trefle_available,
            "inaturalist_available": inaturalist_available,
            "any_available": any_available,
            "perenual_at_limit": perenual_at_limit,
            "trefle_at_limit": trefle_at_limit,
            "inaturalist_at_limit": inaturalist_at_limit,
            "perenual_calls": perenual_calls,
            "trefle_calls": trefle_calls,
            "inaturalist_calls": inaturalist_calls,
        }

    @property
    def is_on(self) -> bool:
        """Return true if ANY primary API (Perenual or Trefle) is usable.
        
        iNaturalist is enrichment-only, so its availability doesn't affect the main state.
        """
        if self._api is None:
            return False

        status = self._get_api_status()
        return status["any_available"]

    @property
    def icon(self) -> str:
        """Return API connectivity icon."""
        return "mdi:api" if self.is_on else "mdi:api-off"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return API provider status attributes."""
        if self._api is None:
            return {
                "status": "api_client_missing",
                "api_client_loaded": False,
                "api_usable": False,
                "perenual_key_configured": False,
                "trefle_key_configured": False,
                "trefle_enabled": False,
                "inaturalist_enabled": False,
                "perenual_daily_limit": PERENUAL_DAILY_LIMIT,
                "trefle_daily_limit": TREFLE_DAILY_LIMIT,
                "inaturalist_daily_limit": INATURALIST_DAILY_LIMIT,
                "perenual_calls_today": None,
                "perenual_calls_remaining": None,
                "perenual_available": False,
                "perenual_at_limit": False,
                "trefle_calls_today": None,
                "trefle_calls_remaining": None,
                "trefle_available": False,
                "trefle_at_limit": False,
                "inaturalist_calls_today": None,
                "inaturalist_calls_remaining": None,
                "inaturalist_available": False,
                "inaturalist_at_limit": False,
                "any_api_available": False,
                "last_provider": None,
                "last_success": None,
                "last_error": "API client is not loaded",
                "updated_at": dt_util.now().isoformat(),
            }

        # Get comprehensive API status from helper
        api_status = self._get_api_status()
        
        perenual_key = getattr(self._api, "perenual_key", None)
        trefle_key = getattr(self._api, "trefle_key", None)
        enable_trefle = bool(getattr(self._api, "enable_trefle_fallback", False))
        enable_inaturalist = bool(
            getattr(self._api, "enable_inaturalist_enrichment", False)
        )

        perenual_calls_today = api_status["perenual_calls"]
        trefle_calls_today = api_status["trefle_calls"]
        inaturalist_calls_today = api_status["inaturalist_calls"]

        perenual_calls_remaining = max(PERENUAL_DAILY_LIMIT - perenual_calls_today, 0)
        trefle_calls_remaining = max(TREFLE_DAILY_LIMIT - trefle_calls_today, 0)
        inaturalist_calls_remaining = max(INATURALIST_DAILY_LIMIT - inaturalist_calls_today, 0)

        last_error = getattr(self._api, "_last_error", None)
        last_success = getattr(self._api, "_last_success", None)
        last_provider = getattr(self._api, "_last_provider", None)

        perenual_provider = getattr(self._api, "perenual", None)
        trefle_provider = getattr(self._api, "trefle", None)
        inaturalist_provider = getattr(self._api, "inaturalist", None)

        # Determine overall status message
        if not perenual_key and not (enable_trefle and trefle_key):
            status = "no_api_keys_configured"
        elif api_status["perenual_at_limit"] and api_status["trefle_at_limit"]:
            status = "all_limits_reached"
        elif api_status["perenual_at_limit"] and not enable_trefle:
            status = "perenual_limit_reached_no_fallback"
        elif api_status["perenual_at_limit"]:
            status = "perenual_limit_reached_using_trefle"
        elif api_status["trefle_at_limit"] and not api_status["perenual_available"]:
            status = "trefle_limit_reached"
        elif last_error:
            status = "api_error"
        elif api_status["any_available"]:
            status = "connected"
        else:
            status = "unavailable"

        return {
            "status": status,
            "api_client_loaded": True,
            "api_usable": self.is_on,
            # Configuration status
            "perenual_key_configured": bool(perenual_key),
            "trefle_key_configured": bool(trefle_key),
            "trefle_enabled": enable_trefle,
            "inaturalist_enabled": enable_inaturalist,
            # Availability status (new - shows which APIs can be used right now)
            "perenual_available": api_status["perenual_available"],
            "trefle_available": api_status["trefle_available"],
            "inaturalist_available": api_status["inaturalist_available"],
            "any_api_available": api_status["any_available"],
            # Limit status (new - shows which APIs hit their limits)
            "perenual_at_limit": api_status["perenual_at_limit"],
            "trefle_at_limit": api_status["trefle_at_limit"],
            "inaturalist_at_limit": api_status["inaturalist_at_limit"],
            # Daily limits
            "perenual_daily_limit": PERENUAL_DAILY_LIMIT,
            "trefle_daily_limit": TREFLE_DAILY_LIMIT,
            "inaturalist_daily_limit": INATURALIST_DAILY_LIMIT,
            # Call counts
            "perenual_calls_today": perenual_calls_today,
            "perenual_calls_remaining": perenual_calls_remaining,
            "perenual_usage_percent": round(
                (perenual_calls_today / PERENUAL_DAILY_LIMIT) * 100,
                1,
            ),
            "trefle_calls_today": trefle_calls_today,
            "trefle_calls_remaining": trefle_calls_remaining,
            "trefle_usage_percent": round(
                (trefle_calls_today / TREFLE_DAILY_LIMIT) * 100,
                1,
            ),
            "inaturalist_calls_today": inaturalist_calls_today,
            "inaturalist_calls_remaining": inaturalist_calls_remaining,
            "inaturalist_usage_percent": round(
                (inaturalist_calls_today / INATURALIST_DAILY_LIMIT) * 100,
                1,
            ),
            # Last operation details
            "last_provider": last_provider,
            "last_success": last_success,
            "last_error": last_error,
            "perenual_last_error": getattr(perenual_provider, "last_error", None)
            if perenual_provider is not None
            else None,
            "trefle_last_error": getattr(trefle_provider, "last_error", None)
            if trefle_provider is not None
            else None,
            "inaturalist_last_error": getattr(
                inaturalist_provider,
                "last_error",
                None,
            )
            if inaturalist_provider is not None
            else None,
            "base_url": getattr(perenual_provider, "base_url", None)
            if perenual_provider is not None
            else getattr(self._api, "_base_url", None),
            "next_limit_reset": "midnight",  # All limits reset at midnight
            "updated_at": dt_util.now().isoformat(),
        }


class PlantBinaryBase(PlantHelperBinaryBase):
    """Base binary sensor for configured plants."""

    _attr_should_poll = False

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        plant_id: str,
        plant_data: dict[str, Any],
        plant_info: dict[str, Any],
        storage: Any,
        algorithms: PlantCareAlgorithms | None = None,
    ) -> None:
        """Initialize plant binary sensor."""
        super().__init__(hass, entry)
        self._plant_id = plant_id
        self._plant_data = plant_data
        self._plant_info = plant_info
        self._storage = storage
        self._algorithms = algorithms
        self._cached_metrics: dict[str, Any] | None = None

    async def async_added_to_hass(self) -> None:
        """Register event listeners when added to HA."""
        await super().async_added_to_hass()

        # Refresh on species fetch and on every care action (watered,
        # fertilized, inspected). Previously only plant_data_fetched was
        # handled, so marking a plant watered never cleared a "needs water"
        # alert for plants without a physical moisture sensor.
        for event_type in (
            EVENT_PLANT_DATA_FETCHED,
            EVENT_PLANT_WATERED,
            EVENT_PLANT_FERTILIZED,
            EVENT_PLANT_INSPECTED,
            EVENT_USER_PLANT_ADDED,
        ):
            self.async_on_remove(
                self.hass.bus.async_listen(event_type, self._handle_plant_event)
            )

        # Recompute time-dependent metrics on a fixed cadence even when no
        # linked source sensor changes (e.g. modeled drying for sensorless
        # plants).
        self.async_on_remove(
            async_track_time_interval(
                self.hass,
                self._handle_metric_refresh,
                METRIC_REFRESH_INTERVAL,
            )
        )

    @callback
    def _handle_metric_refresh(self, now) -> None:
        """Periodic recompute of time-dependent metrics."""
        if self._algorithms:
            self._algorithms.record_runtime_sample(self._plant_id, self._plant_data)
        self._cached_metrics = None
        self.async_schedule_update_ha_state(True)

    def _refresh_plant_state(self) -> None:
        """Reload this plant's data and species info from storage."""
        latest_plant_data = self._storage.get_user_plant(self._plant_id)
        if latest_plant_data:
            self._plant_data = latest_plant_data
        species = self._plant_data.get("species")
        latest_plant_info = self._storage.get_plant(species) if species else None
        if latest_plant_info:
            self._plant_info = latest_plant_info

    def _metrics(self) -> dict[str, Any]:
        """Get cached metrics or compute them."""
        if self._cached_metrics is None and self._algorithms:
            self._cached_metrics = self._algorithms.compute_metrics(
                self._plant_id,
                self._plant_data,
                self._plant_info,
            )
        return self._cached_metrics or {}

    @callback
    def _handle_plant_event(self, event: Event) -> None:
        """Refresh plant data/species info on care or fetch events."""
        if event.data.get("entry_id") not in (None, self._entry.entry_id):
            return
        if event.data.get("plant_id") not in (None, self._plant_id):
            return

        self._refresh_plant_state()
        self._cached_metrics = None
        self.async_schedule_update_ha_state(True)

    @property
    def device_info(self) -> DeviceInfo:
        """Return plant device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._plant_id)},
            name=self._plant_data.get("custom_name") or self._plant_id,
            manufacturer="Plant Helper",
            model=self._plant_info.get(
                "common_name",
                self._plant_data.get("species", "Unknown"),
            ),
            sw_version=str(self._plant_info.get("care_level", "Unknown")),
        )

    def _get_sensor_value(self, key: str) -> float | None:
        """Get numeric value from linked Home Assistant entity."""
        entity_id = _get_linked_entity(self._plant_data, key)

        if not entity_id:
            return None

        state = self.hass.states.get(entity_id)
        if not state or state.state in ("unknown", "unavailable", "none", None):
            return None

        return _safe_float(state.state)

    def _track_entities(self, keys: tuple[str, ...]) -> None:
        """Track linked entity changes."""
        tracked_entities: list[str] = []

        for key in keys:
            entity_id = _get_linked_entity(self._plant_data, key)
            if entity_id:
                tracked_entities.append(entity_id)

        if tracked_entities:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    tracked_entities,
                    self._handle_sensor_update,
                )
            )

    @callback
    def _handle_sensor_update(self, event: Any) -> None:
        """Handle linked entity update."""
        # Reload plant_data so freshly-recorded care timestamps are reflected.
        self._refresh_plant_state()
        if self._algorithms:
            self._algorithms.record_runtime_sample(self._plant_id, self._plant_data)
        # Clear cached metrics so the next read reflects the new sensor value
        self._cached_metrics = None
        self.async_schedule_update_ha_state(True)


class PlantNeedsWaterSensor(PlantBinaryBase):
    """Binary sensor for water status."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        plant_id: str,
        plant_data: dict[str, Any],
        plant_info: dict[str, Any],
        storage: Any,
        algorithms: PlantCareAlgorithms | None = None,
    ) -> None:
        """Initialize water sensor."""
        super().__init__(hass, entry, plant_id, plant_data, plant_info, storage, algorithms)
        name = plant_data.get("custom_name") or plant_id
        self._attr_name = f"{name} Needs Water"
        self._attr_unique_id = f"{DOMAIN}_{plant_id}_needs_water"
        self._track_entities(("moisture",))

    @property
    def is_on(self) -> bool:
        """Return true if plant needs water (smart physics-based logic)."""
        if not self._algorithms:
            # Fallback to simple threshold check if algorithms unavailable
            moisture = self._get_sensor_value("moisture")
            if moisture is None:
                return False
            thresholds = (self._plant_info or {}).get("thresholds", {})
            moisture_min = thresholds.get("soil_moisture_min", 30)
            return moisture < float(moisture_min)
        
        # Use smart calculated moisture and predictive metrics
        metrics = self._metrics()
        
        # Get calculated moisture (blended or modeled)
        calculated_moisture = metrics.get("calculated_soil_moisture")
        if calculated_moisture is None:
            return False
        
        # Get thresholds
        thresholds = (self._plant_info or {}).get("thresholds", {})
        moisture_min = thresholds.get("soil_moisture_min", 30)
        
        # Get predictive metrics
        days_until_watering = metrics.get("days_until_watering", 999)
        watering_urgency = metrics.get("watering_urgency", 0)
        
        # Smart logic: trigger if any of these conditions:
        # 1. Moisture below minimum threshold
        # 2. Less than 1 day until watering needed
        # 3. Watering urgency high (>= 70/100)
        return (
            calculated_moisture < float(moisture_min)
            or days_until_watering < 1.0
            or watering_urgency >= 70
        )

    @property
    def icon(self) -> str:
        """Return icon."""
        return "mdi:water-alert" if self.is_on else "mdi:water-check"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return attributes with smart watering metrics."""
        if not self._algorithms:
            # Fallback to simple attributes
            thresholds = (self._plant_info or {}).get("thresholds", {})
            return {
                "soil_moisture": self._get_sensor_value("moisture"),
                "soil_moisture_min": thresholds.get("soil_moisture_min", 30),
                "source_entity": _get_linked_entity(self._plant_data, "moisture"),
            }
        
        # Smart metrics from algorithms
        metrics = self._metrics()
        thresholds = (self._plant_info or {}).get("thresholds", {})
        
        return {
            "calculated_soil_moisture": metrics.get("calculated_soil_moisture"),
            "soil_moisture_min": thresholds.get("soil_moisture_min", 30),
            "soil_moisture_source": metrics.get("soil_moisture_source"),
            "days_until_watering": metrics.get("days_until_watering"),
            "watering_urgency": metrics.get("watering_urgency"),
            "drying_rate_per_hour": metrics.get("drying_rate_per_hour"),
            "days_since_watered": metrics.get("days_since_watered"),
            "raw_moisture_sensor": self._get_sensor_value("moisture"),
            "source_entity": _get_linked_entity(self._plant_data, "moisture"),
        }


class PlantLowLightSensor(PlantBinaryBase):
    """Binary sensor for low light status."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        plant_id: str,
        plant_data: dict[str, Any],
        plant_info: dict[str, Any],
        storage: Any,
        algorithms: PlantCareAlgorithms | None = None,
    ) -> None:
        """Initialize low light sensor."""
        super().__init__(hass, entry, plant_id, plant_data, plant_info, storage, algorithms)
        name = plant_data.get("custom_name") or plant_id
        self._attr_name = f"{name} Low Light"
        self._attr_unique_id = f"{DOMAIN}_{plant_id}_low_light"
        self._track_entities(("lux",))

    @property
    def is_on(self) -> bool:
        """Return true if light is below threshold."""
        lux = self._get_sensor_value("lux")

        if lux is None:
            return False

        # Get fresh plant_info from storage to ensure thresholds are current
        species = self._plant_data.get("species")
        fresh_plant_info = self._storage.get_plant(species) if species else {}
        thresholds = (fresh_plant_info or {}).get("thresholds", {})
        
        # Use defaults matching plant_care_algorithms.py
        lux_min = thresholds.get("lux_min") or 1200

        return lux < float(lux_min)

    @property
    def icon(self) -> str:
        """Return icon."""
        return "mdi:weather-sunny-alert" if self.is_on else "mdi:white-balance-sunny"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return attributes."""
        # Get fresh plant_info from storage to ensure thresholds are current
        species = self._plant_data.get("species")
        fresh_plant_info = self._storage.get_plant(species) if species else {}
        thresholds = (fresh_plant_info or {}).get("thresholds", {})
        
        # Use defaults matching plant_care_algorithms.py
        return {
            "lux": self._get_sensor_value("lux"),
            "lux_min": thresholds.get("lux_min") or 1200,
            "source_entity": _get_linked_entity(self._plant_data, "lux"),
        }


class PlantTemperatureIssueSensor(PlantBinaryBase):
    """Binary sensor for temperature issues."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        plant_id: str,
        plant_data: dict[str, Any],
        plant_info: dict[str, Any],
        storage: Any,
        algorithms: PlantCareAlgorithms | None = None,
    ) -> None:
        """Initialize temperature issue sensor."""
        super().__init__(hass, entry, plant_id, plant_data, plant_info, storage, algorithms)
        name = plant_data.get("custom_name") or plant_id
        self._attr_name = f"{name} Temperature Issue"
        self._attr_unique_id = f"{DOMAIN}_{plant_id}_temperature_issue"
        self._track_entities(("temperature",))

    @property
    def is_on(self) -> bool:
        """Return true if temperature is outside threshold."""
        temperature = self._get_sensor_value("temperature")

        if temperature is None:
            return False

        # Get fresh plant_info from storage to ensure thresholds are current
        species = self._plant_data.get("species")
        fresh_plant_info = self._storage.get_plant(species) if species else {}
        thresholds = (fresh_plant_info or {}).get("thresholds", {})
        
        # Use defaults matching plant_care_algorithms.py
        temp_min = thresholds.get("temperature_min") or 16
        temp_max = thresholds.get("temperature_max") or 29

        if temp_min is not None and temperature < float(temp_min):
            return True

        if temp_max is not None and temperature > float(temp_max):
            return True

        return False

    @property
    def icon(self) -> str:
        """Return icon."""
        return "mdi:thermometer-alert" if self.is_on else "mdi:thermometer-check"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return attributes."""
        # Get fresh plant_info from storage to ensure thresholds are current
        species = self._plant_data.get("species")
        fresh_plant_info = self._storage.get_plant(species) if species else {}
        thresholds = (fresh_plant_info or {}).get("thresholds", {})
        
        # Use defaults matching plant_care_algorithms.py
        return {
            "temperature": self._get_sensor_value("temperature"),
            "temperature_min": thresholds.get("temperature_min") or 16,
            "temperature_max": thresholds.get("temperature_max") or 29,
            "source_entity": _get_linked_entity(self._plant_data, "temperature"),
        }