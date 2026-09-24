from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Awaitable, Callable, Mapping

from .config import PlantConfig, ValidationError, replace_editable
from .environment import normalize_physical_state
from .placement import PlacementTransition, decide_placement_transition
from .runtime import RuntimeCollection
from .species import normalize_species_key
from .storage import PlantHelperStorage, StorageConflictError

class EditPlantError(RuntimeError):
    def __init__(self,key: str):
        super().__init__(key); self.key=key

@dataclass(frozen=True,slots=True)
class SpeciesChange:
    kind: str
    old_key: str
    new_key: str

@dataclass(frozen=True,slots=True)
class EditPlantResult:
    plant_uuid: str
    revision: int
    store_version: int
    runtime_generation: int
    placement: PlacementTransition
    species: SpeciesChange
    listeners_replaced: bool
    evaluated: bool
    enrichment_scheduled: bool
    reload_count: int=0

@dataclass(slots=True)
class EditPlantHooks:
    replace_listeners: Callable[[str,dict[str,Any],dict[str,Any]],Awaitable[None]]
    evaluate: Callable[[str],Awaitable[None]]
    handle_placement_change: Callable[[str,PlacementTransition],Awaitable[None]]
    handle_species_change: Callable[[str,SpeciesChange],Awaitable[None]]
    schedule_enrichment: Callable[[str,str],Awaitable[None]]
    schedule_reconciliation: Callable[[str],Awaitable[None]]

def classify_species_change(old: Any,new: Any) -> SpeciesChange:
    old_key=normalize_species_key(str(old or "")); new_key=normalize_species_key(str(new or ""))
    if old_key==new_key: kind="unchanged"
    elif not new_key: kind="cleared"
    elif not old_key: kind="added"
    else: kind="identity_pending"
    return SpeciesChange(kind,old_key,new_key)

async def async_edit_plant(
    *,
    plant_uuid: str,
    expected_revision: int,
    raw: Mapping[str,Any],
    placement: str,
    storage: PlantHelperStorage,
    runtime: RuntimeCollection,
    moisture_reader: Callable[[str],Any],
    destination_baseline_complete: bool,
    hooks: EditPlantHooks,
) -> EditPlantResult:
    """Replace all editable fields and update runtime only after persistence."""
    try:
        current_snapshot=await storage.async_get_plant(plant_uuid)
    except Exception:
        raise
    if current_snapshot.revision!=expected_revision:
        raise EditPlantError("plant_changed")
    try:
        current=PlantConfig.normalize(current_snapshot.record,plant_uuid=plant_uuid,revision=current_snapshot.revision)
        merged=dict(raw); merged["placement"]=placement
        replacement=replace_editable(current,merged)
    except ValidationError as err:
        raise EditPlantError(err.key) from None

    moisture=normalize_physical_state(moisture_reader(replacement.soil_moisture),minimum=0,maximum=100)
    if moisture.status=="invalid": raise EditPlantError("moisture_not_numeric")
    if moisture.status=="out_of_range": raise EditPlantError("moisture_out_of_range")

    placement_change=decide_placement_transition(current.placement,replacement.placement,destination_baseline_complete=destination_baseline_complete)
    species_change=classify_species_change(current.species,replacement.species)
    record=asdict(replacement)
    try:
        saved=await storage.async_replace_plant(plant_uuid,expected_revision,record)
    except StorageConflictError:
        raise EditPlantError("plant_changed") from None

    runtime_plant=runtime.update(plant_uuid,saved.record)
    if moisture.status=="valid": runtime_plant.state["moisture"]=moisture.value
    listeners=False; evaluated=False; enrichment=False
    try:
        await hooks.replace_listeners(plant_uuid,current_snapshot.record,saved.record); listeners=True
        if placement_change.changed:
            await hooks.handle_placement_change(plant_uuid,placement_change)
        if species_change.kind!="unchanged":
            await hooks.handle_species_change(plant_uuid,species_change)
        await hooks.evaluate(plant_uuid); evaluated=True
    except Exception:
        try:
            await hooks.schedule_reconciliation(plant_uuid)
        except Exception:
            # Persistence already succeeded. Startup restoration remains authoritative.
            pass

    if replacement.species and species_change.kind!="unchanged":
        try:
            await hooks.schedule_enrichment(plant_uuid,replacement.species); enrichment=True
        except Exception:
            enrichment=False

    return EditPlantResult(plant_uuid,saved.revision,saved.store_version,runtime_plant.generation,placement_change,species_change,listeners,evaluated,enrichment,0)
