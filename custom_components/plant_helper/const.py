"""Constants for Plant Helper."""

DOMAIN = "plant_helper"

STORAGE_KEY = "plant_helper.storage"
STORAGE_VERSION = 1


CONF_UPDATE_INTERVAL = "update_interval"
CONF_PERENUAL_API_KEY = "perenual_api_key"
CONF_TREFLE_API_KEY = "trefle_api_key"
CONF_ENABLE_TREFLE_FALLBACK = "enable_trefle_fallback"
CONF_ENABLE_INATURALIST_ENRICHMENT = "enable_inaturalist_enrichment"

DEFAULT_UPDATE_INTERVAL = 300
DEFAULT_ENABLE_TREFLE_FALLBACK = True
DEFAULT_ENABLE_INATURALIST_ENRICHMENT = True

ATTR_SPECIES = "species"
ATTR_COMMON_NAME = "common_name"
ATTR_THRESHOLDS = "thresholds"
ATTR_TIPS = "tips"
ATTR_FACTS = "facts"


PERENUAL_DAILY_LIMIT = 100
TREFLE_DAILY_LIMIT = 500
INATURALIST_DAILY_LIMIT = 300

# Events
EVENT_PLANT_ADDED = "plant_helper_plant_added"
EVENT_PLANT_REMOVED = "plant_helper_plant_removed"
EVENT_PLANT_DATA_FETCHED = "plant_helper_plant_data_fetched"
EVENT_USER_PLANT_ADDED = "plant_helper_user_plant_added"
EVENT_USER_PLANT_REMOVED = "plant_helper_user_plant_removed"
EVENT_PLANT_WATERED = "plant_helper_watered"
EVENT_PLANT_FERTILIZED = "plant_helper_fertilized"
EVENT_PLANT_INSPECTED = "plant_helper_inspected"
EVENT_DATABASE_RESET = "plant_helper_database_reset"

# --- v4 engine configuration ---------------------------------------------
CONF_PLACEMENT = "placement"
CONF_PROFILE = "profile"
CONF_BATTERY_ENTITY = "battery_entity"
CONF_RAIN_LIMIT_MM = "rain_limit_mm"
CONF_FORECAST_ENTITY = "forecast_entity"

PLACEMENTS = ["indoor", "outdoor"]
PROFILES = ["dry_tolerant", "balanced", "moisture_loving", "custom"]
DEFAULT_PLACEMENT = "indoor"
DEFAULT_PROFILE = "balanced"
DEFAULT_RAIN_LIMIT_MM = 1.0

# Maps the config_flow's stored entity keys to the engine's sensor keys.
ENGINE_SENSOR_MAP = {
    "moisture": "soil_moisture",
    "soil_temp": "soil_temperature",
    "lux": "room_lux",
    "battery": "battery",
}

# Optional outdoor ozone advisory (air quality). Unset = feature off.
CONF_OZONE_ENTITY = "ozone_entity"

# Integration author (shown as the device "manufacturer" / "by ..." in HA).
AUTHOR = "Peter Skopa (@swetoast)"

# STRÅNG radiation source: 'auto' (API in Nordic coverage, else sensors),
# 'api' (always fetch from SMHI), or 'sensors' (read HA STRÅNG sensors).
CONF_RADIATION_SOURCE = "radiation_source"
DEFAULT_RADIATION_SOURCE = "auto"
RADIATION_SOURCES = ["auto", "api", "sensors"]
