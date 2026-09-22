from pathlib import Path
import json
ROOT=Path(__file__).parents[2]
def test_release_documentation_exists_and_is_linked():
 required=('docs/INSTALLATION.md','docs/ENTITIES.md','docs/SERVICES.md','docs/TROUBLESHOOTING.md','CHANGELOG.md')
 for name in required:assert (ROOT/name).is_file() and (ROOT/name).read_text().strip()
 readme=(ROOT/'README.md').read_text()
 for name in required[:4]:assert name in readme
def test_readme_is_end_user_focused_and_has_no_personal_defaults():
 text=(ROOT/'README.md').read_text();assert 'Settings > Devices & services' in text and 'custom_components/plant_helper' in text
 for forbidden in ('10.0.0.5','Peter Skopa','/home/peter','example.invalid'):assert forbidden not in text
def test_service_documentation_matches_implementation():
 assert not (ROOT/'custom_components/plant_helper/services.yaml').exists()
 assert 'does not register Home Assistant service actions' in (ROOT/'docs/SERVICES.md').read_text()
def test_changelog_matches_manifest_version():
 version=json.loads((ROOT/'custom_components/plant_helper/manifest.json').read_text())['version']
 assert f'## {version} - ' in (ROOT/'CHANGELOG.md').read_text()
