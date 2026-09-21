"""New care dimensions: profile-weighted health, humidity advisory, absolute light
adequacy. All advisory — none override calibration. Run: python3 tests/test_care_dimensions.py"""
import sys, types
from datetime import datetime, timezone
from pathlib import Path
_ROOT=Path(__file__).resolve().parents[1]
if "plant_helper" not in sys.modules:
    pkg=types.ModuleType("plant_helper"); pkg.__path__=[str(_ROOT)]; sys.modules["plant_helper"]=pkg
if str(_ROOT.parent) not in sys.path: sys.path.insert(0,str(_ROOT.parent))
from plant_helper.engine import health as hp, humidity as hu, light_model as lm  # noqa: E402
UTC=timezone.utc
def check(n,c): assert c, f"FAILED: {n}"; print(f"  PASS  {n}")

print("== profile-weighted health ==")
# dry soil + great light: succulent scores higher than moisture-lover
dry=hp.evaluate_health(moisture_score=70,light_score=100,thermal_score=90,profile="dry_tolerant").score
wet=hp.evaluate_health(moisture_score=70,light_score=100,thermal_score=90,profile="moisture_loving").score
bal=hp.evaluate_health(moisture_score=70,light_score=100,thermal_score=90,profile="balanced").score
check("dry_tolerant > balanced > moisture_loving when soil dry-ish + light great", dry>bal>wet)
check("unknown profile falls back to balanced",
      hp.evaluate_health(moisture_score=70,light_score=100,thermal_score=90,profile="weird").score==bal)
check("weights renormalise with a missing pillar",
      hp.evaluate_health(moisture_score=80,light_score=None,thermal_score=90,profile="dry_tolerant").score is not None)

print("== humidity advisory (species-gated, indoor-only, advisory) ==")
check("humidity-lover in dry air -> low", hu.assess_humidity(35.0,prefers_humidity=True,placement="indoor").state=="low")
check("humidity-lover in very dry air -> very_low", hu.assess_humidity(25.0,prefers_humidity=True,placement="indoor").state=="very_low")
check("succulent never nagged", hu.assess_humidity(20.0,prefers_humidity=False,placement="indoor").state=="ok")
check("your 80% reads ok", hu.assess_humidity(80.0,prefers_humidity=True,placement="indoor").state=="ok")
check("outdoor -> not_applicable", hu.assess_humidity(20.0,prefers_humidity=True,placement="outdoor").state=="not_applicable")
check("no reading -> not_applicable", hu.assess_humidity(None,prefers_humidity=True,placement="indoor").state=="not_applicable")
check("invalid % -> not_applicable", hu.assess_humidity(150.0,prefers_humidity=True,placement="indoor").state=="not_applicable")

print("== absolute light adequacy (the 'wrong location' catch) ==")
t=datetime(2026,9,5,12,tzinfo=UTC)
spot506=[lm.IndoorLightObservation(t,40.0,506.0,200.0) for _ in range(8)]
check("506 lx OK for low_light", lm.species_light_adequacy(spot506,"low_light").state=="ok")
check("506 lx OK for bright_indirect (floor 500)", lm.species_light_adequacy(spot506,"bright_indirect").state=="ok")
check("506 lx under_lit for full_sun", lm.species_light_adequacy(spot506,"full_sun").state=="under_lit")
check("no light preference -> no_reference", lm.species_light_adequacy(spot506,None).state=="no_reference")
check("too few bright observations -> no_reference", lm.species_light_adequacy([],"full_sun").state=="no_reference")
bright=[lm.IndoorLightObservation(t,40.0,3000.0,200.0) for _ in range(8)]
check("3000 lx OK for full_sun", lm.species_light_adequacy(bright,"full_sun").state=="ok")

print("\nALL CARE-DIMENSION TESTS PASSED")


def test_care_dimensions_reject_non_finite_inputs():
    """NaN must never become a healthy score or a silent actionable reading."""
    from plant_helper.engine import air_quality as aq
    from plant_helper.engine import dormancy as dorm
    from plant_helper.engine import health
    from plant_helper.engine import humidity

    result = health.evaluate_health(
        moisture_score=float("nan"),
        light_score=50.0,
        thermal_score=None,
    )
    assert result.score == 50.0
    assert result.components == {"light": 50.0}

    humidity_result = humidity.assess_humidity(
        float("nan"), prefers_humidity=True, placement="indoor"
    )
    assert humidity_result.state == humidity.NOT_APPLICABLE
    assert humidity_result.humidity_pct is None

    ozone_result = aq.assess_air_quality(
        ozone_ugm3=float("nan"), placement="outdoor"
    )
    assert ozone_result.advisory == aq.NONE
    assert ozone_result.ozone_ugm3 is None

    dormancy_result = dorm.evaluate_dormancy(
        par_slope_30d=float("nan"),
        soil_temp_slope_30d=-0.2,
        currently_dormant=False,
        days_in_state=30,
    )
    assert dormancy_result.reason == "insufficient_data"
