import json
from pathlib import Path

def test_manifest_and_translations_parse():
 root=Path(__file__).parents[2]/"custom_components"/"plant_helper"
 manifest=json.loads((root/"manifest.json").read_text())
 strings=json.loads((root/"strings.json").read_text())
 translation=json.loads((root/"translations"/"en.json").read_text())
 assert manifest["domain"]=="plant_helper" and manifest["config_flow"] is True
 assert strings==translation
 assert {"invalid","invalid_global_settings"} <= strings["config"]["error"].keys()

def test_config_flow_contains_safe_form_recovery():
 source=(Path(__file__).parents[2]/"custom_components"/"plant_helper"/"config_flow.py").read_text()
 assert "self._abort_if_unique_id_configured()" in source
 assert 'errors["base"]="invalid_global_settings"' in source
 assert "add_suggested_values_to_schema" in source
