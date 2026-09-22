import json
from pathlib import Path

def test_options_adapter_commits_real_add_and_preserves_errors():
 root=Path(__file__).parents[1]/"custom_components"/"plant_helper"
 source=(root/"options.py").read_text()
 assert "await async_add_plant(" in source
 assert "phase_9_not_implemented" not in source
 assert 'errors["base"]="cannot_save_plant"' in source
 assert "add_suggested_values_to_schema(schema,user_input)" in source
 assert "self._clear_transient()" in source

def test_add_translations_are_complete():
 root=Path(__file__).parents[1]/"custom_components"/"plant_helper"
 strings=json.loads((root/"strings.json").read_text()); english=json.loads((root/"translations"/"en.json").read_text())
 assert strings==english
 errors=strings["options"]["error"]
 assert {"moisture_not_ready","moisture_not_numeric","moisture_out_of_range","cannot_save_plant"} <= errors.keys()

def test_runtime_owns_phase9_hooks():
 source=(Path(__file__).parents[1]/"custom_components"/"plant_helper"/"runtime.py").read_text()
 for name in ("storage","register_listeners","evaluate","schedule_enrichment","schedule_reconciliation"):
  assert name in source
