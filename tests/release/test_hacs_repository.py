from pathlib import Path
import json
ROOT=Path(__file__).parents[2]
def test_hacs_repository_layout():
 assert json.loads((ROOT/'hacs.json').read_text())['name']=='Plant Helper'
 integrations=[p for p in (ROOT/'custom_components').iterdir() if p.is_dir()]
 assert [p.name for p in integrations]==['plant_helper']
 assert (integrations[0]/'manifest.json').is_file()
def test_hacs_manifest_required_metadata_present():
 manifest=json.loads((ROOT/'custom_components/plant_helper/manifest.json').read_text())
 for key in ('domain','documentation','issue_tracker','codeowners','name','version'):assert manifest.get(key)
def test_brand_assets_are_valid_png_files():
 from PIL import Image
 for name,size in (('icon.png',(256,256)),('icon@2x.png',(512,512))):
  with Image.open(ROOT/'custom_components/plant_helper/brand'/name) as image:assert image.format=='PNG' and image.size==size
def test_github_workflows_and_maintenance_plan_exist():
 workflow=(ROOT/'.github/workflows/validate.yml').read_text();assert 'hacs/action@main' in workflow and 'home-assistant/actions/hassfest@master' in workflow
 assert (ROOT/'docs/POST_RELEASE_MAINTENANCE.md').is_file()
def test_internal_phase_documents_are_not_in_public_tree():
 assert not list(ROOT.glob('PHASE_*')) and not list(ROOT.glob('PLANT_HELPER_*PLAN.md'))
