import pytest
from domain.setup_flow import SetupAborted,SetupCreated,SetupFlowModel,SetupForm
import copy
from domain.options_flow import PlantOptionsFlowModel,OptionsMenu,PlacementForm,PlantForm,RemoveConfirmation
from domain.reconfigure_flow import ReconfigureFlowModel,ReconfigureForm,ReconfigureUpdated

# ---- from test_setup_flow_model.py ----
def test_start_defaults_and_duplicate():
 model=SetupFlowModel(); result=model.start(existing_entry=False)
 assert isinstance(result,SetupForm) and result.defaults=={"perenual_access_level":"free","update_interval":300}
 assert model.start(existing_entry=True)==SetupAborted("single_instance_allowed")

def test_minimum_create():
 result=SetupFlowModel().submit({"perenual_access_level":"free","update_interval":300},existing_entry=False)
 assert result==SetupCreated("Plant Helper","plant_helper",{}, {"perenual_access_level":"free","update_interval":300})

def test_full_create_normalizes_and_trims():
 result=SetupFlowModel().submit({"latitude":"57.72","longitude":"12.94","perenual_api_key":" key ","perenual_access_level":"paid","trefle_api_key":" token ","update_interval":"600"},existing_entry=False)
 assert isinstance(result,SetupCreated)
 assert result.options["latitude"]==57.72 and result.options["perenual_api_key"]=="key" and result.options["trefle_api_key"]=="token" and result.options["update_interval"]==600

@pytest.mark.parametrize("raw,key",[
 ({"perenual_access_level":"free","update_interval":30},"update_interval"),
 ({"perenual_access_level":"bad","update_interval":300},"perenual_access_level"),
 ({"perenual_access_level":"free","update_interval":300,"latitude":91},"latitude"),
])
def test_errors_stay_on_form(raw,key):
 result=SetupFlowModel().submit(raw,existing_entry=False)
 assert isinstance(result,SetupForm) and result.errors=={key:"invalid"} and result.defaults==raw

def test_duplicate_submit_aborts_without_validation():
 result=SetupFlowModel().submit({"bad":"data"},existing_entry=True)
 assert result==SetupAborted("single_instance_allowed")


# ---- from test_options_flow_model.py ----
PLANTS={
 "a":{"display_name":"Snake Plant","placement":"indoor","revision":3,"soil_moisture":"sensor.a","rain_limit_mm":99},
 "b":{"display_name":"Snake Plant","placement":"outdoor","revision":5,"soil_moisture":"sensor.b","rain_limit_mm":2},
}

def test_menu_has_only_three_actions():
 assert PlantOptionsFlowModel({}).menu()==OptionsMenu(("add","edit","remove"))

def test_add_placement_controls_fields_without_mutation():
 source=copy.deepcopy(PLANTS); model=PlantOptionsFlowModel(source)
 assert model.start_add()==PlacementForm("add")
 indoor=model.choose_add_placement("indoor")
 assert isinstance(indoor,PlantForm) and "rain_limit_mm" not in indoor.fields
 outdoor=model.choose_add_placement("outdoor")
 assert "rain_limit_mm" in outdoor.fields
 assert source==PLANTS

def test_edit_selector_uses_uuid_and_context_labels():
 model=PlantOptionsFlowModel(PLANTS); selector=model.selector("edit")
 assert selector.choices==(("a","Snake Plant · Indoor"),("b","Snake Plant · Outdoor"))

def test_edit_flow_holds_uuid_revision_and_placement_locally():
 model=PlantOptionsFlowModel(PLANTS)
 assert model.select_edit("b")==PlacementForm("edit","b")
 form=model.choose_edit_placement("outdoor")
 assert form.selected_plant_uuid=="b" and form.expected_revision==5
 assert model.state.selected_plant_uuid=="b" and model.state.expected_revision==5
 assert form.suggestions["rain_limit_mm"]==2

def test_indoor_edit_filters_legacy_rain_threshold():
 model=PlantOptionsFlowModel(PLANTS); model.select_edit("a")
 form=model.choose_edit_placement("indoor")
 assert "rain_limit_mm" not in form.fields and "rain_limit_mm" not in form.suggestions

def test_remove_requires_confirmation_with_revision():
 confirmation=PlantOptionsFlowModel(PLANTS).select_remove("b")
 assert confirmation==RemoveConfirmation("b","Snake Plant",5)

def test_cancellation_clears_all_transient_state_and_mutates_nothing():
 original=copy.deepcopy(PLANTS); model=PlantOptionsFlowModel(PLANTS)
 model.select_edit("b"); model.choose_edit_placement("outdoor"); model.stage_input({"display_name":"Changed"})
 menu=model.cancel()
 assert menu==OptionsMenu() and model.state.current_step=="closed"
 assert model.state.selected_plant_uuid is None and model.state.expected_revision is None
 assert model.state.placement is None and model.state.pending_form_input=={}
 assert PLANTS==original

def test_missing_plant_and_invalid_placement_fail_without_mutation():
 model=PlantOptionsFlowModel(PLANTS)
 with pytest.raises(KeyError,match="plant_not_found"): model.select_edit("missing")
 model.start_add()
 with pytest.raises(ValueError,match="placement"): model.choose_add_placement("garden")
 assert PLANTS["a"]["revision"]==3


# ---- from test_reconfigure_flow_model.py ----
def test_open_uses_existing_normalized_values():
 current={"latitude":57.72,"longitude":12.94,"perenual_api_key":"key","perenual_access_level":"paid","trefle_api_key":"token","update_interval":600}
 result=ReconfigureFlowModel().open(current)
 assert result==ReconfigureForm(current,{})

def test_open_invalid_legacy_values_falls_back_safely():
 result=ReconfigureFlowModel().open({"latitude":"nan","perenual_access_level":"bad"})
 assert result.suggestions=={"perenual_access_level":"free","update_interval":300} and result.errors=={}

def test_complete_replacement_clears_all_optionals():
 current={"latitude":57.72,"longitude":12.94,"perenual_api_key":"key","perenual_access_level":"paid","trefle_api_key":"token","update_interval":600}
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
