from pathlib import Path
def test_runtime_owns_learning_service():
 src=(Path(__file__).parents[1]/'custom_components'/'plant_helper'/'runtime.py').read_text();assert 'learning: Any=None' in src
def test_learning_uses_separate_store_sections():
 src=(Path(__file__).parents[1]/'custom_components'/'plant_helper'/'domain'/'learning.py').read_text()
 assert 'async_set_learned' in src and 'async_set_active_samples' in src
 assert "self.baselines.setdefault(uuid,{})[placement]" in src
