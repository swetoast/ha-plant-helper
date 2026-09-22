import json
from pathlib import Path

def test_reconfigure_adapter_contract():
 source=(Path(__file__).parents[2]/"custom_components"/"plant_helper"/"config_flow.py").read_text()
 assert "self._get_reconfigure_entry()" in source
 assert "async_update_reload_and_abort(entry,options=options)" in source
 assert "suggestions=entry.options if user_input is None else user_input" in source
 assert 'step_id="reconfigure"' in source

def test_reconfigure_translations_complete():
 root=Path(__file__).parents[2]/"custom_components"/"plant_helper"
 strings=json.loads((root/"strings.json").read_text())
 english=json.loads((root/"translations"/"en.json").read_text())
 assert strings==english
 user=set(strings["config"]["step"]["user"]["data"])
 reconfigure=set(strings["config"]["step"]["reconfigure"]["data"])
 assert user==reconfigure
 assert strings["config"]["abort"]["reconfigure_successful"]
