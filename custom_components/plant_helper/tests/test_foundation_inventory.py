"""Foundation inventory: every production module and public symbol must be owned by tests."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Every current production module belongs to a behavioral foundation area.
MODULE_OWNERS = {
    "__init__.py": "integration lifecycle and services",
    "api/__init__.py": "provider exports",
    "api/base.py": "provider primitives and rate limiting",
    "api/inaturalist.py": "iNaturalist transport and normalization",
    "api/perenual.py": "Perenual access levels, transport, and normalization",
    "api/trefle.py": "Trefle transport and botanical normalization",
    "binary_sensor.py": "binary entity contracts",
    "config_flow.py": "initial configuration behavior",
    "options.py": "options and plant lifecycle behavior",
    "const.py": "public constants and defaults",
    "coordinator.py": "coordinator collection and orchestration",
    "engine/__init__.py": "engine exports",
    "engine/accumulator.py": "time-series accumulation",
    "engine/air_quality.py": "air-quality assessment",
    "engine/calibration_math.py": "calibration mathematics",
    "engine/dormancy.py": "dormancy state",
    "engine/engine.py": "care engine orchestration",
    "engine/health.py": "plant health assessment",
    "engine/humidity.py": "humidity assessment",
    "engine/light_model.py": "light assessment",
    "engine/moisture_model.py": "moisture assessment",
    "engine/precedence.py": "state precedence",
    "engine/thermal_model.py": "thermal assessment",
    "engine/timeseries.py": "time-series analysis",
    "engine/util.py": "numeric utilities",
    "engine/validation.py": "sensor and care validation",
    "enrichment.py": "species enrichment and insight",
    "entity.py": "shared entity contract",
    "learned_store.py": "learned state persistence",
    "plant_config.py": "plant configuration validation",
    "plant_data_api.py": "provider orchestration and cache",
    "runtime.py": "runtime reduction and learning",
    "sample_store.py": "sample persistence",
    "sensor.py": "sensor entity contracts",
    "sources/__init__.py": "source exports",
    "sources/forecast.py": "Home Assistant forecast parsing",
    "sources/open_meteo.py": "Open-Meteo parsing and transport",
    "storage.py": "configuration persistence",
}

# Public definitions are explicit so a new unowned production feature fails this test.
PUBLIC_SYMBOLS = {
    "__init__.py": {"async_setup", "async_setup_entry", "async_unload_entry"},
    "api/base.py": {"ProviderResult", "RateLimiter", "normalize_text", "first_value"},
    "api/inaturalist.py": {"INaturalistProvider"},
    "api/perenual.py": {"PerenualProvider"},
    "api/trefle.py": {"TrefleProvider"},
    "binary_sensor.py": {"PlantNeedsWaterBinary", "PlantWeatherHazardBinary", "PlantSensorFaultBinary", "PlantObstructionBinary", "PlantDormantBinary", "PlantOzoneAdvisoryBinary", "RadiationSourceIssueBinary", "ApiHealthBinary", "async_setup_entry"},
    "config_flow.py": {"PlantHelperConfigFlow"},
    "options.py": {"PlantHelperOptionsFlow"},
    "coordinator.py": {"PlantHelperCoordinator"},
    "engine/accumulator.py": {"Sample", "Interval", "window", "valid_intervals", "accumulate_minutes", "integrate", "daily_dli", "time_weighted_mean", "extent", "covered_minutes", "coverage_ratio", "rolling_average", "rolling_max_average", "robust_median", "latest_ts", "nearest_value", "daily_dli_by_date", "complete_day_dli", "complete_day_light_hours"},
    "engine/air_quality.py": {"AirQualityAssessment", "assess_air_quality"},
    "engine/calibration_math.py": {"saturated_peak", "average_daily_drying", "dry_threshold", "nudge_peak", "dli_baseline", "WindowSample", "DailyRecord", "band_for_elevation", "resolve_k", "window_factor_by_elevation", "window_factor_scalar", "reduce_window_observations", "thermal_mean", "diurnal_swing", "CalibrationResult", "synthesize_calibration"},
    "engine/dormancy.py": {"DormancyResult", "evaluate_dormancy"},
    "engine/engine.py": {"EngineInputs", "EngineResult", "th_daily_dli", "compute"},
    "engine/health.py": {"HealthResult", "evaluate_health"},
    "engine/humidity.py": {"HumidityAssessment", "assess_humidity"},
    "engine/light_model.py": {"LightAssessment", "evaluate_light_outdoor", "IndoorLightObservation", "evaluate_light_indoor", "indoor_light_hours", "LightAdequacyAssessment", "species_light_adequacy"},
    "engine/moisture_model.py": {"detect_watering", "last_watering", "rain_expected", "temperature_compensate", "MoistureAssessment", "evaluate_moisture"},
    "engine/precedence.py": {"Precedence", "resolve_precedence"},
    "engine/thermal_model.py": {"ForecastHour", "ThermalAssessment", "evaluate_thermal", "detect_hazard", "aggregate_forecast_precip", "max_forecast_precip_probability", "cloud_factor", "drying_modifier_from_cloud", "drying_modifier_from_forecast", "drying_modifier_from_et0", "combine_drying_modifiers"},
    "engine/timeseries.py": {"windowed_mean", "TrendResult", "trend", "duration_where", "current_run_minutes", "min_max", "StepEvent", "detect_sustained_step"},
    "engine/util.py": {"to_float", "parse_iso", "daylight_hours"},
    "engine/validation.py": {"RawReading", "ValidationSpec", "validate_series", "BatteryStatus", "battery_status", "current_reading_stale", "CareGate", "care_gate"},
    "enrichment.py": {"reference_watering_days", "suggested_profile", "summarize_enrichment", "merge_provider_data", "species_data_quality", "light_preference", "species_insight"},
    "entity.py": {"hub_device_info", "PlantEntity"},
    "learned_store.py": {"empty_data", "migrate", "set_config", "get_config", "get_placement", "set_baseline", "active_baseline", "has_baseline", "swap_placement", "set_calibration", "get_calibration", "set_dormancy", "get_dormancy", "reset_placement", "remove_plant", "append_daily", "get_daily", "set_last_reduced", "get_last_reduced", "get_timer", "set_timer", "LearnedStore"},
    "plant_config.py": {
        "next_revision",
        "normalize_global_options",
        "replace_global_options",
        "slug",
        "unique_plant_id",
        "validate_plant",
        "split_record",
    },
    "plant_data_api.py": {"PlantDataAPI"},
    "runtime.py": {"reduce_day", "serialize_day_record", "deserialize_day_record", "advance_calibration", "adapt_locked_baseline", "is_calibrating", "advance_dormancy", "build_indoor_observations", "daily_field_slope", "recent_dli_means", "timer_duration", "update_timer", "build_engine_inputs"},
    "sample_store.py": {"empty_data", "append_reading", "prune_series", "raw_readings", "latest", "clear_key_prefix", "SampleStore"},
    "sensor.py": {"PlantHealthSensor", "PlantCareActionSensor", "PlantMoistureStateSensor", "PlantLightStateSensor", "PlantThermalStateSensor", "PlantCalibrationSensor", "PlantSpeciesInfoSensor", "async_setup_entry"},
    "sources/forecast.py": {"parse_forecast", "parse_forecast_from_attributes", "async_fetch_forecast"},
    "sources/open_meteo.py": {"OutdoorContext", "radiation_series", "parse_response", "fetch_context"},
    "storage.py": {"PlantStorage"},
}


def _production_modules() -> set[str]:
    return {
        path.relative_to(ROOT).as_posix()
        for path in ROOT.rglob("*.py")
        if "tests" not in path.parts and "__pycache__" not in path.parts
    }


def _public_definitions(relative: str) -> set[str]:
    tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and not node.name.startswith("_")
    }


def test_every_production_module_has_a_foundation_owner() -> None:
    assert _production_modules() == set(MODULE_OWNERS)
    assert all(owner.strip() for owner in MODULE_OWNERS.values())


def test_every_public_definition_is_in_the_foundation_inventory() -> None:
    for relative in sorted(_production_modules()):
        actual = _public_definitions(relative)
        expected = PUBLIC_SYMBOLS.get(relative, set())
        assert actual == expected, f"Update foundation ownership for {relative}: actual={sorted(actual)} expected={sorted(expected)}"


def test_legacy_phase_test_names_are_gone() -> None:
    names = {path.name for path in Path(__file__).parent.glob("test_*.py")}
    assert not any(name.startswith("test_phase") for name in names)
