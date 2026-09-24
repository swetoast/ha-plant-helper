from __future__ import annotations
from domain.entity_contract import *
from domain.physical import BATTERY_STATES, normalize_battery_state
from domain.entity_contract import BY_KEY, SENSORS

# ---- from test_entity_contract.py ----
def test_final_meaningful_entity_set():
 assert tuple(x.key for x in SENSORS)==('care_status','moisture','light','temperature','humidity','battery','health','calibration','species_context')
 assert tuple(x.key for x in BINARY_SENSORS)==('needs_attention',)
 assert not ({'provider_status','api_status','debug','cache','generation'} & set(BY_KEY))
def test_stable_unique_and_entity_ids():
 assert unique_id('entry','a'*32,'care_status')=='entry_'+'a'*32+'_care_status'
 assert suggested_entity_id('Living Room Palm','care_status')=='living_room_palm_care_status'
 assert suggested_entity_id('Åsa’s Palm','moisture')=='asas_palm_moisture'
def test_units_device_classes_and_state_classes():
 expected={'moisture':('%','moisture','measurement'),'light':('lx','illuminance','measurement'),'temperature':('°C','temperature','measurement')}
 for key,values in expected.items():
  item=BY_KEY[key];assert (item.unit,item.device_class,item.state_class)==values
 assert BY_KEY['needs_attention'].device_class=='problem'
 for key in ('care_status','health','calibration','species_context'):assert BY_KEY[key].unit is None and BY_KEY[key].state_class is None
def test_minimal_attributes_and_no_provider_debug_clutter():
 state={'care_status_attributes':{'summary':'Water soon','reason':'drying','provider':'x','debug':{'x':1},'generation':7},'species_context_attributes':{'scientific_name':'Dracaena trifasciata','family':'Asparagaceae','image_url':'/api/plant_helper/image/hash','providers':['x'],'raw':{}}}
 assert attributes_for(BY_KEY['care_status'],state)=={'summary':'Water soon','reason':'drying'}
 assert attributes_for(BY_KEY['species_context'],state)=={'scientific_name':'Dracaena trifasciata','family':'Asparagaceae','image_url':'/api/plant_helper/image/hash'}
def test_meaningful_states_and_availability():
 state={'care_status':'needs_water','moisture':42.5,'needs_attention':True,'health':'good','calibration':'learning'}
 assert available(False,state,'care_status') and available(False,state,'moisture') and not available(False,state,'light')
 assert not available(True,state,'care_status')
 state['health']='unavailable';assert not available(False,state,'health')
def test_contract_validation():validate_contract()


# ---- from test_battery_contract_011.py ----
def test_verified_categorical_battery_contract_is_exact():
    assert BATTERY_STATES == {"low", "middle", "high"}
    assert normalize_battery_state("low") == "low"
    assert normalize_battery_state("middle") == "middle"
    assert normalize_battery_state("high") == "high"
    assert normalize_battery_state("empty") is None
    assert normalize_battery_state("full") is None


def test_numeric_battery_contract_is_zero_through_one_hundred():
    assert normalize_battery_state(0) == 0.0
    assert normalize_battery_state("100") == 100.0
    assert normalize_battery_state(-1) is None
    assert normalize_battery_state(101) is None


# ---- from test_missing_entities_and_calibration_012.py ----
def test_humidity_entity_contract_is_meaningful():
    humidity = BY_KEY["humidity"]
    assert humidity in SENSORS
    assert humidity.platform == "sensor"
    assert humidity.name == "Humidity"
    assert humidity.unit == "%"
    assert humidity.device_class == "humidity"
    assert humidity.state_class == "measurement"


def test_battery_entity_contract_supports_mixed_verified_source_formats():
    battery = BY_KEY["battery"]
    assert battery in SENSORS
    assert battery.platform == "sensor"
    assert battery.name == "Battery"
    assert battery.unit is None
    assert battery.device_class is None
    assert battery.state_class is None


def test_calibration_entity_exposes_only_a_summary_attribute():
    calibration = BY_KEY["calibration"]
    assert calibration.attributes == ("summary",)


def test_new_entity_ids_follow_existing_contract_without_renaming_old_entities():
    keys = [item.key for item in SENSORS]
    assert "humidity" in keys
    assert "battery" in keys
    for existing in (
        "care_status",
        "moisture",
        "light",
        "temperature",
        "health",
        "calibration",
        "species_context",
    ):
        assert existing in keys


# ---- from test_battery_source_regression_010.py ----
import asyncio
import json
from pathlib import Path

from domain.physical import PlantPhysicalProcessor
from domain.runtime import RuntimeCollection

ROOT = Path(__file__).parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "soil_sensors"


def fixture_entity(file_name: str, entity_id: str) -> dict:
    payload = json.loads((FIXTURES / file_name).read_text())
    return next(item for item in payload["entities"] if item["entity_id"] == entity_id)


def test_real_soil_sensor_battery_shapes_are_normalized_without_inventing_values():
    categorical = fixture_entity(
        "soil_sensor_primary.json", "sensor.soil_sensor_battery_state"
    )
    numeric = fixture_entity(
        "soil_sensor_secondary.json", "sensor.soil_sensor_2_battery"
    )
    assert normalize_battery_state(categorical["state"]) == "middle"
    assert normalize_battery_state(numeric["state"]) == 100.0
    assert normalize_battery_state("unknown") is None
    assert normalize_battery_state("not-a-battery-state") is None


def test_categorical_battery_state_is_preserved_in_runtime():
    runtime = RuntimeCollection()
    runtime.add("plant", {"display_name": "Fixture plant"})
    evaluations = []

    async def evaluate(plant_uuid, environment):
        evaluations.append((plant_uuid, environment))

    processor = PlantPhysicalProcessor(runtime, evaluate, lambda _uuid: {})

    async def scenario():
        assert processor.accept("plant", "battery", "middle")
        await asyncio.sleep(0.4)

    asyncio.run(scenario())
    assert runtime.plants["plant"].state["battery"] == "middle"
    assert evaluations == [("plant", {})]


# ---- P5: status entity carries universal value for both placements ----
def test_care_status_exposes_universal_signals_for_both_placements():
    allowed = BY_KEY['care_status'].attributes
    # the value-for-both core is always allowed
    for name in ('summary', 'reason', 'since', 'confidence', 'drying_context', 'placement'):
        assert name in allowed

    indoor = {'care_status_attributes': {
        'summary': 'Soil moisture is within the selected care profile',
        'reason': 'moisture_in_range', 'since': '2026-01-15T12:00:00+00:00',
        'confidence': 'medium', 'drying_context': 'normal', 'placement': 'indoor',
        'external_daylight': 120.0,
        'rain_suppression': None, 'frost_hours': None, 'exposure': None}}
    result = attributes_for(BY_KEY['care_status'], indoor)
    assert result['confidence'] == 'medium' and result['drying_context'] == 'normal'
    assert result['external_daylight'] == 120.0
    assert 'rain_suppression' not in result and 'frost_hours' not in result  # None dropped

    outdoor = {'care_status_attributes': {
        'summary': 'Soil is below the profile, but rain is expected soon; watering is paused',
        'reason': 'rain_expected', 'since': '2026-01-15T12:00:00+00:00',
        'confidence': 'high', 'drying_context': 'high', 'placement': 'outdoor',
        'rain_suppression': True, 'frost_hours': 2, 'exposure': ['frost'],
        'external_daylight': None}}
    result = attributes_for(BY_KEY['care_status'], outdoor)
    assert result['rain_suppression'] is True and result['frost_hours'] == 2
    assert result['exposure'] == ['frost'] and 'external_daylight' not in result
