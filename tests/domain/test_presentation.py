"""Pure parts of the Home Assistant presentation: repairs, daily light, settings."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from domain.edit_plant import setting_change
from domain.enrichment import ProviderError, SourceEnrichment
from domain.issues import desired_issues
from domain.temporal.daily import DailySummary, light_report
from domain.temporal.light import DailyLightExposure

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
PLANT = {"display_name": "Snake Plant", "soil_moisture": "sensor.soil", "species": "Dracaena trifasciata", "species_sources": {"inaturalist": "skip"}}


def _issues(plants, **kwargs):
    base = {"sensor_exists": lambda _entity: True, "provider_problems": {}, "perenual_free": True}
    base.update(kwargs)
    return desired_issues(plants, **base)


def test_no_issues_for_a_healthy_setup():
    assert _issues({"a": PLANT}) == {}


def test_missing_moisture_sensor_is_only_judged_after_startup():
    assert _issues({"a": PLANT}, sensor_exists=lambda _entity: False) == {
        "missing_moisture_sensor_a": ("missing_moisture_sensor", {"plant": "Snake Plant", "entity_id": "sensor.soil"})
    }
    assert _issues({"a": PLANT}, sensor_exists=None) == {}


def test_plants_on_the_old_name_matching_are_listed_together():
    legacy = dict(PLANT, species_sources=None)
    other = dict(legacy, display_name="Monstera")
    no_species = dict(PLANT, species=None, species_sources=None)
    issues = _issues({"a": legacy, "b": other, "c": no_species})
    assert issues == {"plants_not_rematched": ("plants_not_rematched", {"plants": "Snake Plant, Monstera"})}


def test_rejected_key_and_plan_mismatch():
    issues = _issues({}, provider_problems={"trefle": "auth", "perenual": "plan"}, perenual_free=False)
    assert issues["provider_key_rejected_trefle"] == ("provider_key_rejected", {"provider": "Trefle"})
    assert issues["perenual_plan_mismatch"] == ("perenual_plan_mismatch", {})
    # On the free plan a paywalled record is expected, not a problem.
    assert _issues({}, provider_problems={"perenual": "plan"}, perenual_free=True) == {}


class _Adapter:
    def __init__(self):
        self.error: ProviderError | None = None

    async def record(self, _species_id):
        if self.error is not None:
            raise self.error
        return {"watering_category": "Minimum"}


def test_enrichment_remembers_the_last_auth_or_plan_problem_until_a_fetch_succeeds():
    adapter = _Adapter()
    enrichment = SourceEnrichment(perenual=adapter)
    adapter.error = ProviderError("auth", 401)
    asyncio.run(enrichment.enrich({"perenual": {"id": 1}}, now=NOW))
    assert enrichment.problems == {"perenual": "auth"}
    adapter.error = None
    enrichment.cache.clear()
    asyncio.run(enrichment.enrich({"perenual": {"id": 1}}, now=NOW))
    assert enrichment.problems == {}
    adapter.error = ProviderError("rate", 429)  # temporary, not a repair
    enrichment.cache.clear()
    asyncio.run(enrichment.enrich({"perenual": {"id": 2}}, now=NOW))
    assert enrichment.problems == {}


def _day(day: str, natural: float, artificial: float, effective: float) -> DailySummary:
    light = DailyLightExposure(
        day_date=day, daylight_start=None, daylight_end=None, daylight_classification_certain=True,
        natural_light_exposure=natural, artificial_light_exposure=artificial,
        effective_light_exposure=effective, artificial_weight_applied=0.6, confidence="high",
        classification="normal", daily_peak_lux=900.0, valid_coverage_hours=24.0,
        mean_outdoor_radiation=None,
    )
    empty = {field: None for field in DailySummary.__dataclass_fields__}
    empty.update({key: 0.0 for key in empty if key.endswith("_hours")})
    empty.update(day=day, light=light)
    return DailySummary(**empty)


def test_daily_light_reports_yesterday_and_a_rounded_running_total():
    ledger = {"2026-09-25": _day("2026-09-25", 3000.4, 500.0, 3300.4), "2026-09-26": _day("2026-09-26", 1234.0, 0.0, 1234.0)}
    value, attributes = light_report(ledger, NOW, timezone.utc)
    assert value == 3300
    assert attributes == {"day": "2026-09-25", "natural": 3000, "supplemental": 500, "classification": "normal", "today_so_far": 1200}
    assert light_report({}, NOW, timezone.utc) == (None, {})


def test_changing_one_setting_keeps_every_other_field():
    config = dict(PLANT, plant_uuid="a" * 32, revision=4, placement="outdoor", profile="balanced", rain_limit_mm=1.0)
    revision, raw, placement = setting_change(config, "rain_limit_mm", 3.5)
    assert (revision, placement) == (4, "outdoor")
    assert raw["rain_limit_mm"] == 3.5 and raw["species_sources"] == PLANT["species_sources"]
    assert not {"plant_uuid", "revision", "placement"} & set(raw)
