import json
from pathlib import Path

def test_options_menu_and_transient_fields():
 root=Path(__file__).parents[1]/"custom_components"/"plant_helper"
 source=(root/"options.py").read_text()
 assert 'MENU_OPTIONS=("add","edit","remove")' in source
 for field in ("_selected_plant_uuid","_expected_revision","_placement","_pending_form_input"):
  assert field in source
 assert 'if placement=="outdoor"' in source
 assert 'vol.Required("rain_limit_mm")' in source

def test_completed_add_edit_and_remove_commits_are_present():
 source=(Path(__file__).parents[1]/"custom_components"/"plant_helper"/"options.py").read_text()
 assert "async_add_plant" in source and "async_edit_plant" in source and "async_remove_plant" in source
 assert 'step_id="confirm_remove"' in source

def test_options_translations_and_flow_hook():
 root=Path(__file__).parents[1]/"custom_components"/"plant_helper"
 strings=json.loads((root/"strings.json").read_text())
 english=json.loads((root/"translations"/"en.json").read_text())
 assert strings==english
 assert tuple(strings["options"]["step"]["init"]["menu_options"])==("add","edit","remove")
 config=(root/"config_flow.py").read_text()
 assert "async_get_options_flow" in config and "PlantHelperOptionsFlow" in config
