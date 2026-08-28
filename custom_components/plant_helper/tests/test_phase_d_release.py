"""Public documentation and release-consistency contracts."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
README = (REPO / "README.md").read_text(encoding="utf-8")
CHANGELOG = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
MANIFEST = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))


def _latest_changelog_version() -> str:
    match = re.search(r"^## \[(\d+\.\d+\.\d+)\]", CHANGELOG, re.MULTILINE)
    assert match is not None, "CHANGELOG has no semantic-version release heading"
    return match.group(1)


def test_release_version_is_consistent_everywhere() -> None:
    version = _latest_changelog_version()
    assert MANIFEST["version"] == version
    assert f"version-{version}-blue" in README
    assert f"Version {version}" in README


def test_configuration_docs_match_runtime() -> None:
    assert "default 300" in README
    assert "60–3600" in README
    assert "room temperature" not in README.lower()
    assert "room humidity" not in README.lower()
    for field in (
        "Soil moisture",
        "Soil temperature",
        "Light (lux)",
        "Battery level",
        "Radiation source",
    ):
        assert field in README


def test_services_are_documented() -> None:
    assert "### `plant_helper.recalibrate`" in README
    assert "### `plant_helper.refresh_species`" in README
    assert "omit it to refresh every configured plant" in README
    assert "does not reset calibration or change care decisions" in README


def test_health_calibration_behavior_is_documented() -> None:
    sensor = (ROOT / "sensor.py").read_text(encoding="utf-8")
    assert "if not r or r.calibrating:" in sensor
    assert "Health sensor is unavailable during calibration" in README
    assert "separate **Calibration** diagnostic" in README


def test_readme_is_end_user_focused() -> None:
    forbidden = (
        "QUALITY_ROADMAP.md",
        "LEARNING_LIFECYCLE.md",
        "docs/HACS.md",
        "BUILD_PLAN.md",
        "field-proven",
        "field-verified",
        "repository-level Home Assistant contracts",
        "real Home Assistant test-load",
    )
    for text in forbidden:
        assert text not in README
    assert README.count("[CHANGELOG.md](CHANGELOG.md)") == 1
