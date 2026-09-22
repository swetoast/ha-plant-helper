import json
from pathlib import Path

def test_options_adapter_has_full_edit_navigation_and_commit():
 root=Path(__file__).parents[2]/"custom_components"/"plant_helper"; source=(root/"options.py").read_text()
 for step in ("async_step_edit","async_step_edit_placement","async_step_edit_plant"):
  assert step in source
 assert "await async_edit_plant(" in source and "phase_10_not_implemented" not in source
 assert '_expected_revision=int(selected.config["revision"])' in source
 assert "self._clear_transient()" in source

def test_edit_translations_complete():
 root=Path(__file__).parents[2]/"custom_components"/"plant_helper"
 strings=json.loads((root/"strings.json").read_text()); english=json.loads((root/"translations"/"en.json").read_text())
 assert strings==english
 assert {"edit","edit_placement","edit_plant"} <= strings["options"]["step"].keys()
 assert "plant_changed" in strings["options"]["error"] and "plant_not_found" in strings["options"]["abort"]

def test_runtime_owns_edit_hooks():
 source=(Path(__file__).parents[2]/"custom_components"/"plant_helper"/"runtime.py").read_text()
 for name in ("replace_listeners","handle_placement_change","handle_species_change","destination_baseline_complete"):
  assert name in source
