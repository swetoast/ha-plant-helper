import re, pytest
from domain.config import GlobalSettings, PlantConfig, ValidationError, new_plant_uuid, replace_editable

def test_global_minimum_and_clear():
    assert GlobalSettings.normalize({}).to_options()=={"perenual_access_level":"free","update_interval":300}
    assert GlobalSettings.normalize({"perenual_api_key":"  ","latitude":""}).to_options()=={"perenual_access_level":"free","update_interval":300}

@pytest.mark.parametrize("raw,key", [({"latitude":float("nan")},"latitude"),({"longitude":181},"longitude"),({"update_interval":True},"update_interval"),({"perenual_access_level":"x"},"perenual_access_level")])
def test_invalid_globals(raw,key):
    with pytest.raises(ValidationError) as err: GlobalSettings.normalize(raw)
    assert err.value.key==key

def test_uuid_and_indoor_outdoor_normalization():
    uid=new_plant_uuid(); assert re.fullmatch(r"[0-9a-f]{32}",uid)
    indoor=PlantConfig.normalize({"display_name":" A ","soil_moisture":"sensor.m","placement":"indoor","profile":"balanced"},plant_uuid=uid)
    assert indoor.display_name=="A" and indoor.rain_limit_mm is None
    outdoor=PlantConfig.normalize({"display_name":"A","soil_moisture":"sensor.m","placement":"outdoor","profile":"custom","custom_multiplier":1.5,"rain_limit_mm":2},plant_uuid=uid)
    assert outdoor.rain_limit_mm==2 and outdoor.custom_multiplier==1.5

def test_complete_replacement_clears_optionals():
    uid="a"*32
    old=PlantConfig.normalize({"display_name":"A","soil_moisture":"sensor.m","placement":"outdoor","profile":"custom","custom_multiplier":1,"rain_limit_mm":2,"lux":"sensor.l"},plant_uuid=uid)
    new=replace_editable(old,{"display_name":"B","soil_moisture":"sensor.m","placement":"indoor","profile":"balanced"})
    assert new.plant_uuid==uid and new.revision==2 and new.lux is None and new.rain_limit_mm is None and new.custom_multiplier is None
