from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Awaitable, Callable, Mapping, Protocol

from .config import PlantConfig, ValidationError, new_plant_uuid
from .environment import normalize_physical_state
from .runtime import RuntimeCollection
from .storage import PlantHelperStorage, PlantSnapshot

class MoistureReader(Protocol):
    def __call__(self, entity_id: str) -> Any: ...

class AddPlantError(RuntimeError):
    def __init__(self,key: str):
        super().__init__(key); self.key=key

@dataclass(frozen=True,slots=True)
class AddPlantResult:
    plant_uuid: str
    revision: int
    store_version: int
    runtime_generation: int
    listeners_registered: bool
    entities_requested: bool
    evaluated: bool
    enrichment_scheduled: bool
    reload_count: int = 0

@dataclass(slots=True)
class AddPlantHooks:
    register_listeners: Callable[[str,dict[str,Any]],Awaitable[None]]
    request_entities: Callable[[str],Awaitable[None]]
    evaluate: Callable[[str],Awaitable[None]]
    schedule_enrichment: Callable[[str,str],Awaitable[None]]
    schedule_reconciliation: Callable[[str],Awaitable[None]]

async def async_add_plant(
    *,
    raw: Mapping[str,Any],
    placement: str,
    storage: PlantHelperStorage,
    runtime: RuntimeCollection,
    moisture_reader: MoistureReader,
    hooks: AddPlantHooks,
    uuid_factory: Callable[[],str]=new_plant_uuid,
) -> AddPlantResult:
    """Validate, persist revision 1, then activate the plant without a reload."""
    merged=dict(raw); merged["placement"]=placement
    try:
        plant_uuid=uuid_factory()
        config=PlantConfig.normalize(merged,plant_uuid=plant_uuid,revision=1)
    except ValidationError as err:
        raise AddPlantError(err.key) from None

    moisture=normalize_physical_state(moisture_reader(config.soil_moisture),minimum=0,maximum=100)
    if moisture.status=="unavailable": raise AddPlantError("moisture_not_ready")
    if moisture.status=="invalid": raise AddPlantError("moisture_not_numeric")
    if moisture.status=="out_of_range": raise AddPlantError("moisture_out_of_range")

    record=asdict(config)
    saved: PlantSnapshot=await storage.async_add_plant(plant_uuid,record)
    runtime_plant=runtime.add(plant_uuid,saved.record)

    listeners=False; entities=False; evaluated=False; enrichment=False
    try:
        await hooks.register_listeners(plant_uuid,saved.record); listeners=True
        await hooks.request_entities(plant_uuid); entities=True
        runtime_plant.state["moisture"]=moisture.value
        await hooks.evaluate(plant_uuid); evaluated=True
    except Exception:
        try:
            await hooks.schedule_reconciliation(plant_uuid)
        except Exception:
            # Persistence already succeeded. Startup restoration remains authoritative.
            pass

    species=saved.record.get("species")
    if species:
        try:
            await hooks.schedule_enrichment(plant_uuid,str(species)); enrichment=True
        except Exception:
            # Enrichment is optional and cannot invalidate a committed plant.
            enrichment=False

    return AddPlantResult(
        plant_uuid,1,saved.store_version,runtime_plant.generation,
        listeners,entities,evaluated,enrichment,0,
    )
