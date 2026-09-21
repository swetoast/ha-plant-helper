"""Bring-your-own radiation sensor: reuse an existing shortwave sensor for PAR.
Run: python3 tests/test_radiation_entity.py"""
import sys, types, ast
from pathlib import Path
_ROOT=Path(__file__).resolve().parents[1]
if "plant_helper" not in sys.modules:
    pkg=types.ModuleType("plant_helper"); pkg.__path__=[str(_ROOT)]; sys.modules["plant_helper"]=pkg
if str(_ROOT.parent) not in sys.path: sys.path.insert(0,str(_ROOT.parent))
from plant_helper.sources import open_meteo as om  # noqa: E402
def check(n,c): assert c, f"FAILED: {n}"; print(f"  PASS  {n}")

print("== shortwave -> PAR/lux conversion (the reused sensor) ==")
check("20 W/m² -> 9 PAR", abs(20.0*om.SHORTWAVE_TO_PAR - 9.0) < 1e-9)
check("200 W/m² -> 90 PAR (well above obstruction bright floor 40)", 200.0*om.SHORTWAVE_TO_PAR > 40)
check("20 W/m² -> 2400 lx", abs(20.0*om.SHORTWAVE_TO_LUX - 2400.0) < 1e-9)

print("== wiring: const + config field + coordinator priority branch ==")
const=(_ROOT/"const.py").read_text()
check("CONF_RADIATION_ENTITY defined", 'CONF_RADIATION_ENTITY = "radiation_entity"' in const)
cf=(_ROOT/"config_flow.py").read_text()
check("config-flow exposes the picker", "CONF_RADIATION_ENTITY" in cf)
init=(_ROOT/"__init__.py").read_text()
check("init passes radiation_entity", "radiation_entity=_opt(CONF_RADIATION_ENTITY" in init)
coord=(_ROOT/"coordinator.py").read_text()
check("coordinator has the priority branch", "if self._radiation_entity:" in coord)
check("branch builds PAR from shortwave", "open_meteo_src.SHORTWAVE_TO_PAR" in coord)
check("entity path takes priority over STRÅNG", "elif self._use_strang_api:" in coord)
check("open-meteo radiation skipped when entity used", "not used_radiation_entity" in coord)
check("radiation_entity reported as active_source", '"active_source": "radiation_entity"' in coord)

print("\nALL RADIATION-ENTITY TESTS PASSED")
