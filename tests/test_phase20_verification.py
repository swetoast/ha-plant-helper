from __future__ import annotations
import ast,json
from pathlib import Path
ROOT=Path(__file__).parents[1]

def test_required_phase20_test_areas_are_present():
 names={p.name for p in (ROOT/'tests').glob('test_*.py')}
 required={
  'test_setup_flow_model.py','test_reconfigure_flow_model.py','test_options_flow_model.py',
  'test_storage.py','test_runtime_core.py','test_physical.py','test_learning.py',
  'test_placement_storage.py','test_forecast.py','test_air_quality.py','test_enrichment.py',
  'test_image_proxy.py','test_entity_contract.py','test_entity_registry_assets.py',
 }
 assert required<=names,sorted(required-names)

def test_manifest_is_valid_and_contains_no_placeholder_urls():
 manifest=json.loads((ROOT/'custom_components/plant_helper/manifest.json').read_text())
 assert manifest['domain']=='plant_helper' and manifest['name']=='Plant Helper'
 assert manifest['config_flow'] is True and manifest['iot_class']=='local_push'
 assert manifest['version']=='0.0.3' and isinstance(manifest['requirements'],list)
 assert 'example.invalid' not in json.dumps(manifest)

def test_translation_files_are_valid_and_identical():
 strings=json.loads((ROOT/'custom_components/plant_helper/strings.json').read_text())
 english=json.loads((ROOT/'custom_components/plant_helper/translations/en.json').read_text())
 assert strings==english

def test_python_sources_parse_successfully():
 for path in ROOT.rglob('*.py'):ast.parse(path.read_text(),filename=str(path))

def test_privacy_and_credentials_are_not_exposed_in_user_state_contract():
 contract=(ROOT/'custom_components/plant_helper/domain/entity_contract.py').read_text()
 for token in ('provider','provenance','raw','debug','trace','api_key','token'):
  assert repr(token) in contract
 assert "attributes=('scientific_name','family','image_url')" in contract

def test_image_route_requires_authentication_and_redaction_is_connected():
 image=(ROOT/'custom_components/plant_helper/image_proxy.py').read_text()
 enrichment=(ROOT/'custom_components/plant_helper/domain/enrichment.py').read_text()
 assert 'requires_auth=True' in image
 assert 'redact(err' in enrichment and "'[redacted]'" in enrichment
