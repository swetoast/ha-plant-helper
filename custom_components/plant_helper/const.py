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

EVENT_PLANT_ADDED = f"{DOMAIN}_plant_added"
EVENT_PLANT_REMOVED = f"{DOMAIN}_plant_removed"
EVENT_PLANT_DATA_FETCHED = f"{DOMAIN}_plant_data_fetched"
EVENT_USER_PLANT_ADDED = f"{DOMAIN}_user_plant_added"
EVENT_USER_PLANT_REMOVED = f"{DOMAIN}_user_plant_removed"
EVENT_PLANT_FERTILIZED = f"{DOMAIN}_fertilized"
EVENT_PLANT_INSPECTED = f"{DOMAIN}_inspected"
EVENT_DATABASE_RESET = f"{DOMAIN}_database_reset"