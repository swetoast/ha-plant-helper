from __future__ import annotations
from pathlib import Path
import json
from PIL import Image
import ast
from domain.entity_contract import BY_KEY, attributes_for

# ---- from test_hacs_repository.py ----
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
 for name,size in (('icon.png',(256,256)),('icon@2x.png',(512,512))):
  with Image.open(ROOT/'custom_components/plant_helper/brand'/name) as image:assert image.format=='PNG' and image.size==size
def test_github_workflows_and_maintenance_plan_exist():
 workflow=(ROOT/'.github/workflows/validate.yml').read_text();assert 'hacs/action@main' in workflow and 'home-assistant/actions/hassfest@master' in workflow
 assert (ROOT/'docs/POST_RELEASE_MAINTENANCE.md').is_file()
def test_internal_phase_documents_are_not_in_public_tree():
 assert not list(ROOT.glob('PHASE_*')) and not list(ROOT.glob('PLANT_HELPER_*PLAN.md'))


# ---- from test_package_contract.py ----
"""Package-level contract checks.

Consolidates the manifest, translation, parse-safety, import-hygiene, and
privacy invariants that were previously spread across several source-string
snapshot tests. Assertions here are structural (JSON/AST/import scans) or
behavioral (entity-contract filtering), so they survive refactors instead of
breaking on them.
"""




ROOT = Path(__file__).parents[2]
INTEGRATION = ROOT / "custom_components" / "plant_helper"


def test_manifest_is_valid_and_free_of_placeholders():
    manifest = json.loads((INTEGRATION / "manifest.json").read_text())
    assert manifest["domain"] == "plant_helper"
    assert manifest["name"] == "Plant Helper"
    assert manifest["config_flow"] is True
    assert manifest["iot_class"] == "local_push"
    assert isinstance(manifest["requirements"], list)
    assert "example.invalid" not in json.dumps(manifest)


def test_translation_files_are_identical_with_required_error_keys():
    strings = json.loads((INTEGRATION / "strings.json").read_text())
    english = json.loads((INTEGRATION / "translations" / "en.json").read_text())
    assert strings == english
    assert {"invalid", "invalid_global_settings"} <= strings["config"]["error"].keys()
    assert {
        "moisture_not_ready",
        "moisture_not_numeric",
        "moisture_out_of_range",
        "cannot_save_plant",
    } <= strings["options"]["error"].keys()


def test_every_python_source_parses():
    for path in ROOT.rglob("*.py"):
        ast.parse(path.read_text(), filename=str(path))


def test_no_runtime_import_of_uninstalled_root_package():
    offenders = [
        str(path.relative_to(ROOT))
        for path in INTEGRATION.rglob("*.py")
        if "plant_helper_domain" in path.read_text()
    ]
    assert offenders == []
    assert (INTEGRATION / "domain" / "config.py").is_file()
    assert not (ROOT / "plant_helper_domain").exists()


def test_config_flow_declares_a_home_assistant_config_flow():
    tree = ast.parse((INTEGRATION / "config_flow.py").read_text())
    has_config_flow = any(
        isinstance(node, ast.ClassDef)
        and any(
            isinstance(base, ast.Attribute) and base.attr == "ConfigFlow"
            for base in node.bases
        )
        for node in tree.body
    )
    assert has_config_flow


def test_status_and_species_attributes_strip_provider_and_debug_fields():
    state = {
        "care_status_attributes": {
            "summary": "Water soon",
            "reason": "soil_dry",
            "provider": "x",
            "debug": {"x": 1},
            "generation": 7,
        },
        "species_context_attributes": {
            "scientific_name": "Dracaena trifasciata",
            "family": "Asparagaceae",
            "providers": ["x"],
            "raw": {},
        },
    }
    care = attributes_for(BY_KEY["care_status"], state)
    assert care == {"summary": "Water soon", "reason": "soil_dry"}
    species = attributes_for(BY_KEY["species_context"], state)
    assert "providers" not in species and "raw" not in species
    assert species["scientific_name"] == "Dracaena trifasciata"


def test_image_route_and_provider_error_redaction_are_present():
    # Security canaries: the image route must require auth and provider errors
    # must be redacted before they can reach logs or state.
    image = (INTEGRATION / "image_proxy.py").read_text()
    enrichment = (INTEGRATION / "domain" / "enrichment.py").read_text()
    assert "requires_auth=True" in image.replace(" ", "")
    assert "redact(" in enrichment


# ---- from test_release_documentation.py ----
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
