import pytest
from domain.setup_flow import SetupAborted,SetupCreated,SetupFlowModel,SetupForm

def test_start_defaults_and_duplicate():
 model=SetupFlowModel(); result=model.start(existing_entry=False)
 assert isinstance(result,SetupForm) and result.defaults=={"perenual_access_level":"free","update_interval":300}
 assert model.start(existing_entry=True)==SetupAborted("single_instance_allowed")

def test_minimum_create():
 result=SetupFlowModel().submit({"perenual_access_level":"free","update_interval":300},existing_entry=False)
 assert result==SetupCreated("Plant Helper","plant_helper",{}, {"perenual_access_level":"free","update_interval":300})

def test_full_create_normalizes_and_trims():
 result=SetupFlowModel().submit({"latitude":"57.72","longitude":"12.94","ozone_entity":"sensor.ozone","perenual_api_key":" key ","perenual_access_level":"paid","trefle_api_key":" token ","update_interval":"600"},existing_entry=False)
 assert isinstance(result,SetupCreated)
 assert result.options["latitude"]==57.72 and result.options["perenual_api_key"]=="key" and result.options["trefle_api_key"]=="token" and result.options["update_interval"]==600

@pytest.mark.parametrize("raw,key",[
 ({"perenual_access_level":"free","update_interval":30},"update_interval"),
 ({"perenual_access_level":"bad","update_interval":300},"perenual_access_level"),
 ({"perenual_access_level":"free","update_interval":300,"latitude":91},"latitude"),
 ({"perenual_access_level":"free","update_interval":300,"ozone_entity":"binary_sensor.ozone"},"ozone_entity"),
])
def test_errors_stay_on_form(raw,key):
 result=SetupFlowModel().submit(raw,existing_entry=False)
 assert isinstance(result,SetupForm) and result.errors=={key:"invalid"} and result.defaults==raw

def test_duplicate_submit_aborts_without_validation():
 result=SetupFlowModel().submit({"bad":"data"},existing_entry=True)
 assert result==SetupAborted("single_instance_allowed")
