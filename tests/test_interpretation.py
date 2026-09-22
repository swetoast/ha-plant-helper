from types import SimpleNamespace
import pytest
from plant_helper_domain.interpretation import *
FORECAST={'season':'autumn','day_length':10.5,'solar_phase':'day','current_temperature':8,'derived':{'forecast_precipitation_6h':4,'radiation_24h':120,'et0_24h':5,'vpd_max_48h':1.8,'frost_hours_48h':2,'wet_hours_48h':14,'hazard':True}}
def test_indoor_uses_only_daylight_and_seasonal_context():
 r=interpret('indoor',physical={'soil_temperature':22},forecast=FORECAST,air=SimpleNamespace(current_ozone=150))
 assert r.placement=='indoor' and set(r.conditions)<=INDOOR_ALLOWED
 assert r.conditions=={'external_daylight':120.0,'season':'autumn','day_length':10.5,'solar_phase':'day'}
 for forbidden in ('rain_suppression','drying_context','frost','wetness','modelled_shallow_soil','ozone','exposure'):assert forbidden not in r.conditions
def test_indoor_has_no_cross_contamination_when_outdoor_inputs_change():
 a=interpret_indoor(physical={},forecast=FORECAST,air=SimpleNamespace(current_ozone=150))
 changed={**FORECAST,'derived':{**FORECAST['derived'],'forecast_precipitation_6h':100,'et0_24h':30,'vpd_max_48h':5,'frost_hours_48h':30,'wet_hours_48h':40}}
 b=interpret_indoor(physical={},forecast=changed,air=SimpleNamespace(current_ozone=500))
 assert a.conditions==b.conditions
def test_outdoor_complete_context():
 r=interpret('outdoor',physical={'soil_temperature':8},forecast=FORECAST,air=SimpleNamespace(current_ozone=150),rain_limit_mm=3)
 assert set(r.conditions)==OUTDOOR_KEYS and r.conditions['rain_suppression'] and r.conditions['drying_context']=='high'
 assert r.conditions['outdoor_radiation']==120 and r.conditions['frost']==2 and r.conditions['wetness']==14
 assert not r.conditions['growth_season'] and 0<=r.conditions['modelled_shallow_soil']<=100 and r.conditions['ozone']==150
 assert set(r.conditions['exposure'])=={'frost','prolonged_wetness','high_ozone','weather_hazard'}
def test_outdoor_missing_collectors_degrades_locally():
 r=interpret_outdoor(physical={'soil_temperature':12},forecast=None,air=None)
 assert not r.conditions['rain_suppression'] and r.conditions['drying_context']=='low' and r.conditions['growth_season'] and r.conditions['ozone'] is None
def test_snapshots_are_immutable():
 r=interpret_indoor(physical={},forecast=FORECAST)
 with pytest.raises(TypeError):r.conditions['x']=1
def test_invalid_placement():
 with pytest.raises(ValueError,match='placement'):interpret('greenhouse',physical={},forecast={})
