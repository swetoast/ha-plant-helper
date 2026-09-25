from __future__ import annotations
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import pytest
from domain.enrichment import PerenualAdapter, ProviderError, TrefleAdapter
from domain.environment import normalize_weather_payload
from domain.forecast import derived
from domain.enrichment import INaturalistAdapter
from domain.environment import normalize_physical_state
import importlib.util

# ---- from test_external_provider_fixtures.py ----
FIXTURES = Path(__file__).parent / "fixtures"


def external_provider_fixtures_load(path: str) -> dict:
    return json.loads((FIXTURES / path).read_text())


def external_provider_fixtures_run(awaitable):
    return asyncio.run(awaitable)


def open_meteo_series():
    raw = external_provider_fixtures_load("open_meteo/boras_three_day_forecast.json")
    hourly = raw["hourly"]
    units = raw["hourly_units"]
    normalized = {
        "time": hourly["time"],
        "temperature": hourly["temperature_2m"],
        "humidity": hourly["relative_humidity_2m"],
        "precipitation": hourly["precipitation"],
        "radiation": hourly["shortwave_radiation"],
        "et0": hourly["et0_fao_evapotranspiration"],
        "units": {
            "temperature": units["temperature_2m"],
            "humidity": units["relative_humidity_2m"],
            "precipitation": units["precipitation"],
            "radiation": units["shortwave_radiation"],
            "et0": units["et0_fao_evapotranspiration"],
        },
    }
    return raw, normalize_weather_payload(
        normalized,
        ("temperature", "humidity", "precipitation", "radiation", "et0"),
    )


def test_open_meteo_fixture_has_parallel_provider_arrays():
    raw = external_provider_fixtures_load("open_meteo/boras_three_day_forecast.json")
    hourly = raw["hourly"]
    expected = len(hourly["time"])
    assert expected == 24
    for key, values in hourly.items():
        assert len(values) == expected, key
    assert raw["timezone"] == "Europe/Stockholm"
    assert raw["utc_offset_seconds"] == 7200


def test_open_meteo_fixture_drives_real_rain_and_wetness_derivations():
    _, series = open_meteo_series()
    result = derived(series, datetime(2026, 9, 23, 23, tzinfo=timezone.utc))
    assert result["forecast_precipitation_24h"] == pytest.approx(15.3)
    assert result["wet_hours_48h"] >= 10
    assert result["frost_hours_48h"] == 0
    assert result["hazard"] is False


def test_open_meteo_modelled_soil_moisture_is_separate_from_plant_percentage():
    raw = external_provider_fixtures_load("open_meteo/boras_three_day_forecast.json")
    values = raw["hourly"]["soil_moisture_0_to_1cm"]
    assert raw["hourly_units"]["soil_moisture_0_to_1cm"] == "m³/m³"
    assert min(values) == pytest.approx(0.238)
    assert max(values) == pytest.approx(0.294)
    assert "soil_moisture_0_to_1cm" not in open_meteo_series()[1].values


def test_perenual_free_details_response_is_accepted_as_one_candidate():
    fixture = external_provider_fixtures_load("perenual/free_details_success.json")
    adapter = PerenualAdapter(lambda _query: asyncio.sleep(0, result=fixture))
    candidates = external_provider_fixtures_run(adapter.search("Abies alba"))
    assert candidates == [{
        "id": 1,
        "scientific_name": "Abies alba",
        "common_name": "European Silver Fir",
        "family": "Pinaceae",
        "genus": "Abies",
        "synonyms": ["Common Silver Fir"],
        "watering_category": "Frequent",
        "sunlight_requirements": ["full sun"],
        "restricted": False,
    }]


def test_perenual_plan_restriction_is_not_treated_as_json_or_not_found():
    fixture = external_provider_fixtures_load("perenual/paid_details_restricted.json")
    adapter = PerenualAdapter(lambda _query: asyncio.sleep(0, result=fixture))
    with pytest.raises(ProviderError) as raised:
        external_provider_fixtures_run(adapter.search("restricted species"))
    assert raised.value.kind == "plan"
    assert raised.value.status == 429


def test_trefle_details_object_is_accepted_and_summary_counter_is_not_trusted():
    fixture = external_provider_fixtures_load("trefle/monstera_deliciosa_details.json")
    adapter = TrefleAdapter(lambda _query: asyncio.sleep(0, result=fixture))
    candidates = external_provider_fixtures_run(adapter.search("Monstera deliciosa"))
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["scientific_name"] == "Monstera deliciosa"
    assert candidate["family"] == "Araceae"
    assert candidate["genus"] == "Monstera"
    assert len(candidate["synonyms"]) == 3
    assert fixture["meta"]["synonyms_count"] == 0


def test_external_fixtures_are_sanitized():
    forbidden = ("token=", "api_key=", "x-amz-credential", "x-amz-signature", "nabu.casa")
    for directory in ("open_meteo", "perenual", "trefle", "inaturalist"):
        for path in (FIXTURES / directory).glob("*.json"):
            text = path.read_text().casefold()
            assert all(item not in text for item in forbidden), path


def test_inaturalist_no_results_is_an_empty_candidate_set():
    fixture = external_provider_fixtures_load("inaturalist/no_results.json")
    candidates = external_provider_fixtures_run(INaturalistAdapter(lambda _query: asyncio.sleep(0, result=fixture)).search("definitely missing"))
    assert fixture["total_results"] == 0
    assert candidates == []


def test_inaturalist_ambiguous_results_preserve_all_candidates():
    fixture = external_provider_fixtures_load("inaturalist/ambiguous_results.json")
    candidates = external_provider_fixtures_run(INaturalistAdapter(lambda _query: asyncio.sleep(0, result=fixture)).search("Snake Plant"))
    assert fixture["total_results"] == 3
    assert [item["scientific_name"] for item in candidates] == [
        "Sansevieria trifasciata",
        "Sansevieria cylindrica",
        "Sansevieria masoniana",
    ]
    assert candidates[0]["image_url"].endswith("/medium.jpeg")


def test_perenual_empty_search_is_an_empty_candidate_set():
    fixture = external_provider_fixtures_load("perenual/empty_search.json")
    candidates = external_provider_fixtures_run(PerenualAdapter(lambda _query: asyncio.sleep(0, result=fixture)).search("definitely missing"))
    assert fixture["total"] == 0
    assert candidates == []


def test_trefle_multiple_candidates_are_not_collapsed_by_the_adapter():
    fixture = external_provider_fixtures_load("trefle/multiple_candidates.json")
    candidates = external_provider_fixtures_run(TrefleAdapter(lambda _query: asyncio.sleep(0, result=fixture)).search("monstera"))
    assert fixture["meta"]["total"] == 91
    assert len(candidates) == 10
    assert candidates[1]["scientific_name"] == "Monstera deliciosa"
    assert candidates[1]["family"] == "Araceae"
    assert len(candidates[1]["synonyms"]) == 8


def test_inaturalist_dracaena_synonym_resolves_to_current_sansevieria_taxon():
    fixture = external_provider_fixtures_load("inaturalist/inaturalist_dracaena_trifasciata.json")
    candidates = external_provider_fixtures_run(INaturalistAdapter(lambda _query: asyncio.sleep(0, result=fixture)).search("Dracaena trifasciata"))
    assert fixture["total_results"] == 1
    assert fixture["results"][0]["matched_term"] == "Dracaena trifasciata"
    assert candidates == [{
        "scientific_name": "Sansevieria trifasciata",
        "common_name": "Snake Plant",
        "family": None,
        "genus": "Sansevieria",
        "synonyms": ["Dracaena trifasciata"],
        "image_url": "https://inaturalist-open-data.s3.amazonaws.com/photos/488135905/medium.jpeg",
        "provider_id": 67710,
        "matched_term": "Dracaena trifasciata",
    }]


# ---- from test_soil_sensor_fixtures.py ----
SOIL_FIXTURES = Path(__file__).parent / "fixtures" / "soil_sensors"


def soil_sensor_fixtures_load(name: str) -> dict:
    return json.loads((SOIL_FIXTURES / name).read_text())


def entities(snapshot: dict) -> dict[str, dict]:
    return {item["entity_id"]: item for item in snapshot["entities"]}


def test_primary_real_sensor_values_are_preserved():
    data = entities(soil_sensor_fixtures_load("soil_sensor_primary.json"))
    assert data["sensor.soil_sensor_soil_moisture"]["state"] == "36"
    assert data["sensor.soil_sensor_temperature"]["state"] == "26"
    assert data["sensor.soil_sensor_humidity"]["state"] == "43"
    assert data["sensor.soil_sensor_illuminance"]["state"] == "256"


def test_secondary_real_sensor_values_are_preserved():
    data = entities(soil_sensor_fixtures_load("soil_sensor_secondary.json"))
    assert data["sensor.soil_sensor_2_soil_moisture"]["state"] == "43"
    assert data["sensor.soil_sensor_2_temperature"]["state"] == "24.9"
    assert data["sensor.soil_sensor_2_humidity"]["state"] == "71"
    assert data["sensor.soil_sensor_2_battery"]["state"] == "100"


def test_real_numeric_values_normalize_for_runtime_ranges():
    primary = entities(soil_sensor_fixtures_load("soil_sensor_primary.json"))
    secondary = entities(soil_sensor_fixtures_load("soil_sensor_secondary.json"))
    cases = (
        (primary["sensor.soil_sensor_soil_moisture"]["state"], 0, 100, 36.0),
        (primary["sensor.soil_sensor_temperature"]["state"], -100, 200, 26.0),
        (primary["sensor.soil_sensor_humidity"]["state"], 0, 100, 43.0),
        (primary["sensor.soil_sensor_illuminance"]["state"], 0, 1000000, 256.0),
        (secondary["sensor.soil_sensor_2_battery"]["state"], 0, 100, 100.0),
    )
    for raw, minimum, maximum, expected in cases:
        result = normalize_physical_state(raw, minimum=minimum, maximum=maximum)
        assert result.status == "valid"
        assert result.value == expected


def test_categorical_battery_state_is_not_misreported_as_numeric():
    primary = entities(soil_sensor_fixtures_load("soil_sensor_primary.json"))
    result = normalize_physical_state(
        primary["sensor.soil_sensor_battery_state"]["state"],
        minimum=0,
        maximum=100,
    )
    assert result.status == "invalid"
    assert result.value is None


def test_control_entities_are_fixture_evidence_not_physical_inputs():
    for fixture in SOIL_FIXTURES.glob("*.json"):
        data = soil_sensor_fixtures_load(fixture.name)
        physical = {
            item["entity_id"]
            for item in data["entities"]
            if item["entity_id"].startswith("sensor.")
            and item.get("attributes", {}).get("device_class")
            in {"battery", "humidity", "illuminance", "moisture", "temperature"}
        }
        assert not any(entity_id.startswith("number.") for entity_id in physical)
        assert not any(entity_id.startswith("select.") for entity_id in physical)


def test_fixtures_contain_no_remote_urls_or_secrets():
    for fixture in SOIL_FIXTURES.glob("*.json"):
        text = fixture.read_text()
        assert "http://" not in text
        assert "https://" not in text
        assert "token" not in text.casefold()
        assert "api_key" not in text.casefold()


# ---- from test_fixture_recorder.py ----
MODULE_PATH = Path(__file__).parents[1] / "tools" / "record_external_provider_fixtures.py"
SPEC = importlib.util.spec_from_file_location("fixture_recorder", MODULE_PATH)
assert SPEC and SPEC.loader
RECORDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RECORDER)


def test_sanitize_removes_credentials_from_nested_values_and_urls():
    secret = "private-key-value"
    payload = {
        "token": secret,
        "nested": [{"url": f"https://example.invalid/image.jpg?token={secret}&size=large"}],
        "message": f"credential={secret}",
    }
    clean = RECORDER.sanitize(payload, (secret,))
    serialized = str(clean)
    assert secret not in serialized
    assert clean["token"] == "[redacted]"
    assert "token=%5Bredacted%5D" in clean["nested"][0]["url"]


def test_sanitize_url_leaves_non_urls_unchanged():
    assert RECORDER.sanitize_url("Monstera deliciosa") == "Monstera deliciosa"
