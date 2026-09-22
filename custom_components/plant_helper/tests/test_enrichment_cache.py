"""Enrichment cache: exact-match only (no cross-contamination) + retry throttles.
Run: python3 tests/test_enrichment_cache.py"""
import sys, types
from datetime import timedelta
from pathlib import Path
_ROOT=Path(__file__).resolve().parents[1]
if "plant_helper" not in sys.modules:
    pkg=types.ModuleType("plant_helper"); pkg.__path__=[str(_ROOT)]; sys.modules["plant_helper"]=pkg
if str(_ROOT.parent) not in sys.path: sys.path.insert(0,str(_ROOT.parent))

# Minimal HA stubs so storage.py imports without Home Assistant installed.
for name in ("homeassistant","homeassistant.core","homeassistant.helpers",
             "homeassistant.helpers.storage","homeassistant.util","homeassistant.util.dt"):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.modules["homeassistant.core"].HomeAssistant=object
sys.modules["homeassistant.helpers.storage"].Store=object
sys.modules["homeassistant.util.dt"].utcnow=lambda: None
sys.modules["homeassistant.util"].dt=sys.modules["homeassistant.util.dt"]

from plant_helper.storage import PlantStorage  # noqa: E402
def check(n,c): assert c, f"FAILED: {n}"; print(f"  PASS  {n}")

s=PlantStorage.__new__(PlantStorage)
s._data={"plants":{
    "snake plant zeylanica":{"common_name":"snake plant zeylanica","scientific_name":"Dracaena zeylanica"},
    "aloe vera":{"common_name":"aloe vera","scientific_name":"Aloe barbadensis"},
    "sansevieria trifasciata":{"common_name":"snake plant","scientific_name":"Dracaena trifasciata"},
}}

print("== cache lookup is EXACT (no substring cross-contamination) ==")
check("'snake plant' does NOT match 'snake plant zeylanica' by substring",
      s.get_plant_by_name("snake plant")["scientific_name"] == "Dracaena trifasciata")  # exact common_name match
check("'aloe' returns nothing (was matching 'aloe vera')", s.get_plant_by_name("aloe") is None)
check("'sansev' partial returns nothing", s.get_plant_by_name("sansev") is None)
check("'zeylanica' partial returns nothing", s.get_plant_by_name("zeylanica") is None)
check("exact species match works", s.get_plant_by_name("aloe vera")["scientific_name"] == "Aloe barbadensis")
check("exact species (scientific key) works",
      s.get_plant_by_name("sansevieria trifasciata")["scientific_name"] == "Dracaena trifasciata")
check("empty search -> None", s.get_plant_by_name("") is None)
check("case-insensitive exact", s.get_plant_by_name("ALOE VERA")["scientific_name"] == "Aloe barbadensis")

print("== enrichment retry throttles present ==")
coord=(_ROOT/"coordinator.py").read_text()
check("short retry interval for unresolved plants",
      "ENRICHMENT_RETRY_INTERVAL = timedelta(minutes=15)" in coord)
check("unresolved plants retried (not blank for 24h)", "unresolved =" in coord and "retry_due" in coord)
check("unresolved force a real fetch", "force = first_run or plant_id in unresolved" in coord)

print("\nALL ENRICHMENT CACHE TESTS PASSED")
