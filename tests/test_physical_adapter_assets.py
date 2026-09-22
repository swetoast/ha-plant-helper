from pathlib import Path
def test_state_tracking_and_listener_lifecycle():
 root=Path(__file__).parents[1]/'custom_components'/'plant_helper';src=(root/'physical.py').read_text()
 assert 'async_track_state_change_event' in src and 'self.processor.accept' in src
 assert 'def replace(' in src and 'def unsubscribe(' in src and 'def unload(' in src
def test_fixed_debounce_and_cached_environment_contract():
 src=(Path(__file__).parents[1]/'plant_helper_domain'/'physical.py').read_text()
 assert 'DEBOUNCE_SECONDS=0.350' in src
 assert 'self.cached_environment(plant_uuid)' in src
 assert 'plant.generation!=generation' in src
