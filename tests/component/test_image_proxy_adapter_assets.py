from pathlib import Path
def test_authenticated_view_contract():
 text=(Path(__file__).parents[2]/'custom_components'/'plant_helper'/'image_proxy.py').read_text()
 assert "url='/api/plant_helper/image/{digest}'" in text and 'requires_auth=True' in text and "headers.get('If-None-Match')" in text
def test_runtime_owns_image_proxy():
 text=(Path(__file__).parents[2]/'custom_components'/'plant_helper'/'runtime.py').read_text();assert 'species_image_proxy: Any = None' in text
