import pytest
from plant_helper_domain.reconfigure_flow import ReconfigureFlowModel,ReconfigureForm,ReconfigureUpdated

def test_open_uses_existing_normalized_values():
 current={"latitude":57.72,"longitude":12.94,"ozone_entity":"sensor.ozone","perenual_api_key":"key","perenual_access_level":"paid","trefle_api_key":"token","update_interval":600}
 result=ReconfigureFlowModel().open(current)
 assert result==ReconfigureForm(current,{})

def test_open_invalid_legacy_values_falls_back_safely():
 result=ReconfigureFlowModel().open({"latitude":"nan","perenual_access_level":"bad"})
 assert result.suggestions=={"perenual_access_level":"free","update_interval":300} and result.errors=={}

def test_complete_replacement_clears_all_optionals():
 current={"latitude":57.72,"longitude":12.94,"ozone_entity":"sensor.ozone","perenual_api_key":"key","perenual_access_level":"paid","trefle_api_key":"token","update_interval":600}
 result=ReconfigureFlowModel().submit({"perenual_access_level":"free","update_interval":300},current)
 assert result==ReconfigureUpdated({"perenual_access_level":"free","update_interval":300},1)

def test_update_normalizes_and_requests_exactly_one_reload():
 result=ReconfigureFlowModel().submit({"latitude":"57.721","longitude":"12.940","perenual_api_key":" k ","perenual_access_level":"paid","trefle_api_key":" t ","update_interval":"900"},{})
 assert isinstance(result,ReconfigureUpdated)
 assert result.reload_count==1 and result.options["perenual_api_key"]=="k" and result.options["update_interval"]==900

@pytest.mark.parametrize("raw,key",[
 ({"perenual_access_level":"bad","update_interval":300},"perenual_access_level"),
 ({"perenual_access_level":"free","update_interval":59},"update_interval"),
 ({"perenual_access_level":"free","update_interval":300,"longitude":181},"longitude"),
])
def test_invalid_submission_no_update_or_reload(raw,key):
 result=ReconfigureFlowModel().submit(raw,{"perenual_access_level":"paid","update_interval":600})
 assert isinstance(result,ReconfigureForm) and result.errors=={key:"invalid"}
 assert not hasattr(result,"reload_count")
