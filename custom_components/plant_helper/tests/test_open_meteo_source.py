"""Pure checks for the Open-Meteo plant context source."""
from plant_helper.sources.open_meteo import HOURLY_VARIABLES, PlantEnvironment

def test_variable_set_is_focused():
    assert "et0_fao_evapotranspiration" in HOURLY_VARIABLES
    assert "vapour_pressure_deficit" in HOURLY_VARIABLES
    assert "soil_temperature_6cm" in HOURLY_VARIABLES
    assert "soil_moisture_3_to_9cm" in HOURLY_VARIABLES
    assert "soil_moisture_9_to_27cm" in HOURLY_VARIABLES
    assert "surface_pressure" not in HOURLY_VARIABLES

def test_attributes_preserve_units():
    context = PlantEnvironment("2026-08-22T09:00",
        {"vapour_pressure_deficit": 0.8}, {"vapour_pressure_deficit": "kPa"})
    attributes = context.attributes()
    assert attributes["source"] == "Open-Meteo"
    assert attributes["units"]["vapour_pressure_deficit"] == "kPa"
