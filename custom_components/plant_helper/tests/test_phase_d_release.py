"""Phase D documentation and release-cleanup contracts."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
README = (REPO / "README.md").read_text(encoding="utf-8")
ROADMAP = (REPO / "docs" / "QUALITY_ROADMAP.md").read_text(encoding="utf-8")

def test_configuration_docs_match_runtime():
    assert "default 300" in README
    assert "60–3600" in README
    assert "room temperature" not in README.lower()
    assert "room humidity" not in README.lower()
    for field in ("Soil moisture", "Soil temperature", "Light (lux)", "Battery level", "Radiation source"):
        assert field in README

def test_refresh_species_is_documented():
    assert "### `plant_helper.refresh_species`" in README
    assert "omit it to refresh every configured plant" in README
    assert "does not reset calibration or change care decisions" in README

def test_health_is_unavailable_during_calibration():
    sensor = (ROOT / "sensor.py").read_text(encoding="utf-8")
    assert "if not r or r.calibrating:" in sensor
    assert "unavailable while calibrating" in README
    assert "separate **Calibration** diagnostic" in README

def test_release_docs_do_not_claim_manual_assertion_total():
    assert "unit assertions" not in README.lower()
    assert "223" not in README

def test_readiness_wording_is_honest():
    assert "automated verification is complete" in README
    assert "real Home\nAssistant test-load remains" in README
    assert "field-proven" in README

def test_phase_d_roadmap_complete_and_version_bumped():
    phase_d = ROADMAP.split("## Phase D", 1)[1].split("## Phase E", 1)[0]
    assert "- [ ]" not in phase_d
    assert phase_d.count("- [x]") == 6
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    assert tuple(map(int, manifest["version"].split("."))) >= (4, 0, 25)
