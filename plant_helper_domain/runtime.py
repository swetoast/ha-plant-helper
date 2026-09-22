from __future__ import annotations
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

@dataclass(slots=True)
class RuntimePlant:
    plant_uuid: str
    config: dict[str,Any]
    generation: int = 0
    removing: bool = False
    state: dict[str,Any] = field(default_factory=dict)

    def replace_config(self, config: dict[str,Any]) -> None:
        self.config=dict(config)
        self.generation+=1

@dataclass(frozen=True,slots=True)
class PlantSetChange:
    added: frozenset[str]
    updated: frozenset[str]
    removed: frozenset[str]

class RuntimeCollection:
    """UUID-keyed runtime collection and platform notification boundary."""
    def __init__(self) -> None:
        self._plants: dict[str,RuntimePlant]={}
        self._entity_to_plant: dict[str,str]={}
        self._listeners: list[Callable[[PlantSetChange],None]]=[]
        self._unloaded=False

    @property
    def plants(self) -> dict[str,RuntimePlant]: return dict(self._plants)
    @property
    def entity_index(self) -> dict[str,str]: return dict(self._entity_to_plant)
    @property
    def unloaded(self) -> bool: return self._unloaded

    def subscribe(self, callback: Callable[[PlantSetChange],None]) -> Callable[[],None]:
        if self._unloaded: raise RuntimeError("runtime_unloaded")
        self._listeners.append(callback)
        active=True
        def unsubscribe() -> None:
            nonlocal active
            if active:
                active=False
                try: self._listeners.remove(callback)
                except ValueError: pass
        return unsubscribe

    def _notify(self, change: PlantSetChange) -> None:
        for listener in tuple(self._listeners): listener(change)

    def load(self, records: dict[str,dict[str,Any]]) -> None:
        if self._plants: raise RuntimeError("already_loaded")
        self._plants={uuid:RuntimePlant(uuid,dict(record)) for uuid,record in records.items()}
        if records: self._notify(PlantSetChange(frozenset(records),frozenset(),frozenset()))

    def add(self, plant_uuid: str, config: dict[str,Any]) -> RuntimePlant:
        if plant_uuid in self._plants: raise ValueError("plant_exists")
        plant=RuntimePlant(plant_uuid,dict(config)); self._plants[plant_uuid]=plant
        self._notify(PlantSetChange(frozenset({plant_uuid}),frozenset(),frozenset()))
        return plant

    def update(self, plant_uuid: str, config: dict[str,Any]) -> RuntimePlant:
        plant=self._plants.get(plant_uuid)
        if plant is None: raise KeyError("plant_not_found")
        plant.replace_config(config)
        self._notify(PlantSetChange(frozenset(),frozenset({plant_uuid}),frozenset()))
        return plant

    def mark_removing(self, plant_uuid: str) -> RuntimePlant:
        plant=self._plants.get(plant_uuid)
        if plant is None: raise KeyError("plant_not_found")
        plant.removing=True; plant.generation+=1
        return plant

    def detach(self, plant_uuid: str) -> RuntimePlant:
        plant=self._plants.pop(plant_uuid,None)
        if plant is None: raise KeyError("plant_not_found")
        for entity_id,owner in tuple(self._entity_to_plant.items()):
            if owner==plant_uuid: del self._entity_to_plant[entity_id]
        return plant

    def notify_removed(self, plant_uuid: str) -> None:
        self._notify(PlantSetChange(frozenset(),frozenset(),frozenset({plant_uuid})))

    def remove(self, plant_uuid: str) -> RuntimePlant:
        plant=self.detach(plant_uuid)
        self.notify_removed(plant_uuid)
        return plant

    def bind_entity(self, entity_id: str, plant_uuid: str) -> None:
        if plant_uuid not in self._plants: raise KeyError("plant_not_found")
        owner=self._entity_to_plant.get(entity_id)
        if owner is not None and owner!=plant_uuid: raise ValueError("entity_owned_by_other_plant")
        self._entity_to_plant[entity_id]=plant_uuid

    def unload(self) -> None:
        self._unloaded=True
        self._listeners.clear()
        self._entity_to_plant.clear()
        self._plants.clear()
