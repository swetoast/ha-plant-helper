import json
from pathlib import Path
def test_remove_flow_and_registry_hooks():
 root=Path(__file__).parents[1]/'custom_components'/'plant_helper';src=(root/'options.py').read_text()
 assert 'await runtime.remove_plant(' in src and 'phase_11_not_implemented' not in src
 assert 'step_id="confirm_remove"' in src
 assert 'await entity.async_remove()' in (root/'runtime.py').read_text()
def test_translations_and_runtime_hooks():
 root=Path(__file__).parents[1]/'custom_components'/'plant_helper';a=json.loads((root/'strings.json').read_text());b=json.loads((root/'translations/en.json').read_text());assert a==b
 src=(root/'runtime.py').read_text()
 for x in ('cancel_tasks','unsubscribe_listeners','block_evaluation','remove_entity_registry','verify_entities_gone','remove_device_registry','remove_owned_state'):assert x in src
