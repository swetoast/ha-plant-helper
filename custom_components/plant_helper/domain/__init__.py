"""Pure Plant Helper domain models with no Home Assistant dependency."""
from .config import GlobalSettings, PlantConfig, ValidationError, new_plant_uuid, replace_editable
from .environment import canonical_location, normalize_physical_state, normalize_weather_payload, derive_weather_windows
from .placement import PlacementTransition, decide_placement_transition
from .species import normalize_species_key, classify_match, merge_provider_fields
from .storage import PlantHelperStorage, StorageError, StorageConflictError, PlantNotFoundError, PlantExistsError, empty_payload

__all__ = [
    "GlobalSettings", "PlantConfig", "ValidationError", "new_plant_uuid", "replace_editable",
    "canonical_location", "normalize_physical_state", "normalize_weather_payload", "derive_weather_windows",
    "PlacementTransition", "decide_placement_transition", "normalize_species_key", "classify_match",
    "merge_provider_fields",
    "PlantHelperStorage", "StorageError", "StorageConflictError", "PlantNotFoundError", "PlantExistsError", "empty_payload",
]
