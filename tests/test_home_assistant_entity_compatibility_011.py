from pathlib import Path

ROOT = Path(__file__).parents[1] / "custom_components" / "plant_helper"


def test_domain_contract_is_not_assigned_as_home_assistant_entity_description():
    source = (ROOT / "entity.py").read_text()
    assert "self._contract=description" in source
    assert "self.entity_description=description" not in source
    assert "attributes_for(self._contract" in source


def test_sensor_properties_are_set_directly_from_internal_contract():
    source = (ROOT / "sensor.py").read_text()
    assert "self._attr_native_unit_of_measurement = description.unit" in source
    assert "self._attr_device_class = description.device_class" in source
    assert "self._attr_state_class = description.state_class" in source


def test_plant_device_is_retained_while_any_registry_entity_references_it():
    source = (ROOT / "runtime.py").read_text()
    check = source.index("entity.device_id == device.id")
    remove = source.index("registry.async_remove_device(device.id)")
    assert check < remove
