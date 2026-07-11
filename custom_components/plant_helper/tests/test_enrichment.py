"""Tests for the enrichment mapper (pure). Run: python3 tests/test_enrichment.py"""

import sys
import types
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if "plant_helper" not in sys.modules:
    _pkg = types.ModuleType("plant_helper")
    _pkg.__path__ = [str(_ROOT)]
    sys.modules["plant_helper"] = _pkg
if str(_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_ROOT.parent))

from plant_helper import enrichment as en  # noqa: E402


def check(name, cond):
    assert cond, f"FAILED: {name}"
    print(f"  PASS  {name}")


print("== empty / missing ==")
check("empty data -> empty summary", en.summarize_enrichment(None) == {})
check("empty dict -> empty summary", en.summarize_enrichment({}) == {})

print("== Perenual-shaped payload ==")
perenual = {
    "provider": "perenual", "common_name": "Snake Plant",
    "scientific_name": ["Dracaena trifasciata"], "cycle": "Perennial",
    "care_level": "Easy", "watering": "Minimum",
    "sunlight": ["part_shade", "full_sun"], "drought_tolerant": True,
    "poisonous_to_pets": 1, "poisonous_to_humans": 0, "indoor": True,
    "description": "A hardy succulent." * 60,
    "default_image": {"regular_url": "https://img/snake.jpg"},
    "watering_general_benchmark": {"value": "12-14", "unit": "days"},
}
s = en.summarize_enrichment(perenual)
check("common name", s["common_name"] == "Snake Plant")
check("scientific name unwrapped", s["scientific_name"] == "Dracaena trifasciata")
check("toxicity to pets -> True", s["poisonous_to_pets"] is True)
check("toxicity to humans -> False", s["poisonous_to_humans"] is False)
check("photo from default_image", s["photo"] == "https://img/snake.jpg")
check("description truncated to 500", len(s["description"]) == 500)
check("benchmark averaged", s["reference_watering_days"] == 13.0)
check("drought tolerant -> dry_tolerant", s["suggested_profile"] == "dry_tolerant")

print("== profile suggestion logic ==")
check("frequent -> moisture_loving", en.suggested_profile({"watering": "Frequent"}) == "moisture_loving")
check("average -> balanced", en.suggested_profile({"watering": "Average"}) == "balanced")
check("high soil moisture -> moisture_loving", en.suggested_profile({"soil_moisture": 8}) == "moisture_loving")
check("low soil moisture -> dry_tolerant", en.suggested_profile({"soil_moisture": 2}) == "dry_tolerant")
check("no signal -> None", en.suggested_profile({}) is None)

print("== watering reference ==")
check("frequent -> 3", en.reference_watering_days({"watering": "Frequent"}) == 3.0)
check("minimum -> 14", en.reference_watering_days({"watering": "Minimum"}) == 14.0)
check("none -> None", en.reference_watering_days({}) is None)

print("== iNaturalist + Trefle ==")
inat = {"provider": "inaturalist", "common_name": "Fern", "photos": ["https://p1.jpg", "https://p2.jpg"]}
check("photo from photos list", en.summarize_enrichment(inat)["photo"] == "https://p1.jpg")
trefle = {"provider": "trefle", "family": "Asparagaceae", "light": 7, "soil_moisture": 5,
          "minimum_temperature_c": 10, "maximum_temperature_c": 30}
ts = en.summarize_enrichment(trefle)
check("trefle light carried", ts["light_requirement_0_10"] == 7)
check("trefle soil-moisture pref carried", ts["soil_moisture_pref_0_10"] == 5)
check("trefle temps carried", ts["min_temperature_c"] == 10 and ts["max_temperature_c"] == 30)
check("trefle mid soil -> balanced", ts["suggested_profile"] == "balanced")


print("== merge_provider_data (uses all three) ==")

per = {"provider": "perenual", "common_name": "Snake Plant", "watering": "Minimum",
       "sunlight": ["full_sun"], "poisonous_to_pets": 1, "drought_tolerant": True,
       "care_level": "Easy", "default_image": {"regular_url": "https://per/img.jpg"}}
inat = {"provider": "inaturalist", "scientific_name": "Dracaena trifasciata",
        "common_name": "mother-in-law's tongue", "photo": "https://inat/photo.jpg",
        "photos": ["https://inat/photo.jpg"], "wikipedia_url": "https://en.wikipedia.org/x",
        "description": "A hardy succulent."}
tre = {"provider": "trefle", "family": {"id": 356, "name": "Asparagaceae", "slug": "asparagaceae"},
       "growth": {"light": 7, "soil_moisture": 3,
                  "minimum_temperature": {"deg_c": 10}, "maximum_temperature": {"deg_c": 30},
                  "ph_minimum": 6.0, "ph_maximum": 7.5}}

m = en.merge_provider_data([per, inat, tre])
check("scientific name from iNaturalist (canonical)", m["scientific_name"] == "Dracaena trifasciata")
check("common name from Perenual", m["common_name"] == "Snake Plant")
check("family extracted to string from Trefle object", m["family"] == "Asparagaceae")
check("care fields from Perenual", m["watering"] == "Minimum" and m["poisonous_to_pets"] == 1)
check("Trefle botanical from nested growth", m["light"] == 7 and m["minimum_temperature_c"] == 10 and m["maximum_temperature_c"] == 30)
check("Trefle pH from nested growth", m["ph_min"] == 6.0 and m["ph_max"] == 7.5)
check("photo prefers iNaturalist (real) over Perenual", m["photo"] == "https://inat/photo.jpg")
check("all three providers listed", m["providers"] == ["perenual", "inaturalist", "trefle"])
check("merged summarizes cleanly", en.summarize_enrichment(m)["suggested_profile"] == "dry_tolerant")
sm = en.summarize_enrichment(m)
check("wikipedia link surfaced", sm["wikipedia_url"] == "https://en.wikipedia.org/x")
check("photo url surfaced (iNat)", sm["photo"] == "https://inat/photo.jpg")
check("family in summary is a string", sm["family"] == "Asparagaceae")

# iNaturalist alone (no API keys) still yields usable identity + photo.
only_inat = en.merge_provider_data([inat])
check("iNat-only merge -> identity + photo (keyless path)",
      only_inat["scientific_name"] == "Dracaena trifasciata" and only_inat["photo"] == "https://inat/photo.jpg")
check("iNat-only providers list", only_inat["providers"] == ["inaturalist"])

# Perenual + iNat, no Trefle.
m2 = en.merge_provider_data([per, inat])
check("photo falls back to iNat when no perenual image",
      en.merge_provider_data([inat])["photo"] == "https://inat/photo.jpg")

print("== Perenual free-tier placeholder rejected ==")
_ph = "https://s3.wasabisys.com/perenual/image/upgrade_access.jpg?X-Amz-Signature=abc"
per_paywall = {"provider": "perenual", "common_name": "Snake Plant",
               "default_image": {"regular_url": _ph}}
inat_photo = {"provider": "inaturalist", "scientific_name": "Dracaena trifasciata",
              "photo": "https://inaturalist.org/photos/1/medium.jpg"}
mp = en.merge_provider_data([per_paywall, inat_photo])
check("placeholder rejected, real iNat photo used", mp["photo"] == "https://inaturalist.org/photos/1/medium.jpg")
# Perenual placeholder alone -> no photo (not a broken 404 link)
only_paywall = en.merge_provider_data([per_paywall])
check("placeholder-only merge -> no photo", "photo" not in only_paywall)
check("summarize drops placeholder", "photo" not in en.summarize_enrichment({"default_image": {"regular_url": _ph}}))
check("two-provider merge lists both", m2["providers"] == ["perenual", "inaturalist"])

print("== source reflects real providers (not local_cache) ==")
check("source lists providers from merge", en.summarize_enrichment(m)["source"] == "perenual, inaturalist, trefle")
check("iNat-only source", en.summarize_enrichment(only_inat)["source"] == "inaturalist")
# A cached read tagged provider=local_cache still shows real providers if present.
cached = {**m, "provider": "local_cache"}
check("cached read still shows real providers as source", en.summarize_enrichment(cached)["source"] == "perenual, inaturalist, trefle")
# Only when there are no providers does it fall back to the provider tag.
check("no providers -> provider tag", en.summarize_enrichment({"common_name": "X", "provider": "local_cache"})["source"] == "local_cache")

print("\nALL ENRICHMENT TESTS PASSED")


print("== corrected pipeline: right sci name -> rich, honest data ==")
_inat = {"provider": "inaturalist", "scientific_name": "Dracaena trifasciata",
         "common_name": "snake plant", "family": "Asparagaceae",
         "photo": "https://inaturalist.org/photos/9/medium.jpg",
         "wikipedia_url": "https://en.wikipedia.org/wiki/Dracaena_trifasciata"}
_per = {"provider": "perenual", "common_name": "Snake Plant",
        "scientific_name": ["Dracaena trifasciata"], "cycle": "Perennial",
        "watering": "Minimum", "sunlight": ["part shade"],
        "default_image": {"regular_url": "https://s3/perenual/image/upgrade_access.jpg"}}
_tre = {"provider": "trefle", "family": {"name": "Asparagaceae"},
        "growth": {"light": 7, "atmospheric_humidity": 4,
                   "minimum_temperature": {"deg_c": 10}, "maximum_temperature": {"deg_c": 35}}}
_s = en.summarize_enrichment(en.merge_provider_data([_inat, _per, _tre]))
check("correct scientific name from autocomplete-shaped iNat", _s["scientific_name"] == "Dracaena trifasciata")
check("real photo, paywall rejected", _s["photo"] == "https://inaturalist.org/photos/9/medium.jpg")
check("Trefle soil moisture via atmospheric_humidity alias", _s["soil_moisture_pref_0_10"] == 4)
check("reference watering from Perenual word", _s["reference_watering_days"] == 14.0)
check("data quality high with 3 real providers", en.species_data_quality(_s) == "high")

print("\nALL ENRICHMENT TESTS PASSED")
