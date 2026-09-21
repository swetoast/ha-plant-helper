"""Open-Meteo radiation contract for indoor and outdoor plants."""
from pathlib import Path
from plant_helper.sources import open_meteo as om
ROOT = Path(__file__).resolve().parents[1]

def test_only_useful_current_radiation_variables_are_requested():
    assert om.CURRENT_RADIATION_VARIABLES == (
        "shortwave_radiation_instant",
        "diffuse_radiation_instant",
    )

def test_open_meteo_supports_both_placements_without_directional_guessing():
    coordinator = (ROOT / "coordinator.py").read_text()
    assert 'self._par_series_key = "global:par:open_meteo"' in coordinator
    assert 'global_irradiance=current_shortwave' in coordinator
    assert 'diffuse_irradiance=context.diffuse_radiation' in coordinator
    assert 'direct_horizontal=None' in coordinator
    assert 'direct_normal=None' in coordinator
    assert 'plant:{plant_id}:lux' in coordinator
    assert 'global_tilted_irradiance' not in coordinator
    assert 'terrestrial_radiation' not in coordinator
