from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from domain.enrichment import PerenualAdapter, ProviderError, TrefleAdapter
from domain.environment import normalize_weather_payload
from domain.forecast import derived

FIXTURES = Path(__file__).parent / "fixtures"


def load(path: str) -> dict:
    return json.loads((FIXTURES / path).read_text())


def run(awaitable):
    return asyncio.run(awaitable)


def open_meteo_series():
    raw = load("open_meteo/boras_three_day_forecast.json")
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
    raw = load("open_meteo/boras_three_day_forecast.json")
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
    raw = load("open_meteo/boras_three_day_forecast.json")
    values = raw["hourly"]["soil_moisture_0_to_1cm"]
    assert raw["hourly_units"]["soil_moisture_0_to_1cm"] == "m³/m³"
    assert min(values) == pytest.approx(0.238)
    assert max(values) == pytest.approx(0.294)
    assert "soil_moisture_0_to_1cm" not in open_meteo_series()[1].values


def test_perenual_free_details_response_is_accepted_as_one_candidate():
    fixture = load("perenual/free_details_success.json")
    adapter = PerenualAdapter(lambda _query: asyncio.sleep(0, result=fixture))
    candidates = run(adapter.search("Abies alba"))
    assert candidates == [{
        "scientific_name": "Abies alba",
        "common_name": "European Silver Fir",
        "family": "Pinaceae",
        "genus": "Abies",
        "synonyms": [],
        "watering_category": "Frequent",
        "sunlight_requirements": ["full sun"],
        "image_url": "https://images.example.invalid/perenual/abies_alba.jpg",
    }]


def test_perenual_plan_restriction_is_not_treated_as_json_or_not_found():
    fixture = load("perenual/paid_details_restricted.json")
    adapter = PerenualAdapter(lambda _query: asyncio.sleep(0, result=fixture))
    with pytest.raises(ProviderError) as raised:
        run(adapter.search("restricted species"))
    assert raised.value.kind == "plan"
    assert raised.value.status == 429


def test_trefle_details_object_is_accepted_and_summary_counter_is_not_trusted():
    fixture = load("trefle/monstera_deliciosa_details.json")
    adapter = TrefleAdapter(lambda _query: asyncio.sleep(0, result=fixture))
    candidates = run(adapter.search("Monstera deliciosa"))
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["scientific_name"] == "Monstera deliciosa"
    assert candidate["family"] == "Araceae"
    assert candidate["genus"] == "Monstera"
    assert len(candidate["synonyms"]) == 3
    assert fixture["meta"]["synonyms_count"] == 0


def test_external_fixtures_are_sanitized():
    forbidden = ("token=", "api_key=", "x-amz-credential", "x-amz-signature", "nabu.casa")
    for directory in ("open_meteo", "perenual", "trefle"):
        for path in (FIXTURES / directory).glob("*.json"):
            text = path.read_text().casefold()
            assert all(item not in text for item in forbidden), path
