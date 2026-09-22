from pathlib import Path
ROOT=Path(__file__).parents[2]
def test_platforms_use_shared_contract_not_key_clutter():
 sensor=(ROOT/'custom_components/plant_helper/sensor.py').read_text();binary=(ROOT/'custom_components/plant_helper/binary_sensor.py').read_text()
 assert 'from .domain.entity_contract import SENSORS' in sensor and 'SENSOR_KEYS=' not in sensor
 assert 'from .domain.entity_contract import BINARY_SENSORS' in binary and 'BINARY_SENSOR_KEYS=' not in binary
def test_dynamic_add_update_remove_registry_lifecycle():
 for name in ('sensor.py','binary_sensor.py'):
  text=(ROOT/'custom_components/plant_helper'/name).read_text();assert 'change.added' in text and 'change.updated' in text and 'change.removed' in text and 'async_remove()' in text
def test_entity_identity_availability_and_minimal_attributes_are_connected():
 text=(ROOT/'custom_components/plant_helper/entity.py').read_text()
 for token in ('unique_id(','suggested_entity_id(','available(','attributes_for('):assert token in text
 assert "'manufacturer':'Plant Helper'" in text
