import copy
import pytest
from plant_helper_domain.options_flow import PlantOptionsFlowModel,OptionsMenu,PlacementForm,PlantForm,RemoveConfirmation

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
