from pathlib import Path

def test_runtime_adapter_uses_runtime_data_and_platform_forwarding():
 root=Path(__file__).parents[2]/"custom_components"/"plant_helper"
 init=(root/"__init__.py").read_text()
 assert "entry.runtime_data=PlantHelperRuntime()" in init
 assert "async_forward_entry_setups" in init and "async_unload_platforms" in init
 assert "await entry.runtime_data.async_unload()" in init

def test_dynamic_platform_contract():
 root=Path(__file__).parents[2]/"custom_components"/"plant_helper"
 for name in ("sensor.py","binary_sensor.py"):
  source=(root/name).read_text()
  assert "runtime.plants.subscribe(handle)" in source
  assert "async_add_entities(created)" in source
  assert "async_create_task(entity.async_remove())" in source
  assert "change.updated" in source and "async_write_ha_state()" in source

def test_entity_identity_contract():
 source=(Path(__file__).parents[2]/"custom_components"/"plant_helper"/"entity.py").read_text()
 assert 'f"{entry_id}_{plant.plant_uuid}_{key}"' in source
 assert '(DOMAIN,plant.plant_uuid)' in source
 assert "_attr_should_poll=False" in source
