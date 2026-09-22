from __future__ import annotations
from dataclasses import dataclass,field
from typing import Any,Mapping

@dataclass(frozen=True,slots=True)
class OptionsMenu:
    choices: tuple[str,...] = ("add","edit","remove")

@dataclass(frozen=True,slots=True)
class PlacementForm:
    operation: str
    selected_plant_uuid: str | None = None

@dataclass(frozen=True,slots=True)
class PlantForm:
    operation: str
    placement: str
    fields: tuple[str,...]
    selected_plant_uuid: str | None
    expected_revision: int | None
    suggestions: dict[str,Any]

@dataclass(frozen=True,slots=True)
class PlantSelector:
    operation: str
    choices: tuple[tuple[str,str],...]

@dataclass(frozen=True,slots=True)
class RemoveConfirmation:
    plant_uuid: str
    display_name: str
    expected_revision: int

@dataclass(slots=True)
class OptionsFlowState:
    selected_plant_uuid: str | None = None
    expected_revision: int | None = None
    placement: str | None = None
    pending_form_input: dict[str,Any] = field(default_factory=dict)
    current_step: str = "init"

    def clear(self) -> None:
        self.selected_plant_uuid=None
        self.expected_revision=None
        self.placement=None
        self.pending_form_input.clear()
        self.current_step="closed"

COMMON_FIELDS=("display_name","soil_moisture","species","soil_temperature","humidity_sensor","lux","battery","profile","custom_multiplier")
OUTDOOR_FIELDS=COMMON_FIELDS+("rain_limit_mm",)

class PlantOptionsFlowModel:
    """Pure navigation model. It never mutates persistent plant storage."""
    def __init__(self,plants: Mapping[str,Mapping[str,Any]]) -> None:
        self._plants={key:dict(value) for key,value in plants.items()}
        self.state=OptionsFlowState()

    def menu(self) -> OptionsMenu:
        self.state.current_step="init"
        return OptionsMenu()

    def start_add(self) -> PlacementForm:
        self.state=OptionsFlowState(current_step="add_placement")
        return PlacementForm("add")

    def choose_add_placement(self,placement: str) -> PlantForm:
        return self._placement_form("add",placement,None,None,{})

    def selector(self,operation: str) -> PlantSelector:
        if operation not in {"edit","remove"}: raise ValueError("operation")
        self.state=OptionsFlowState(current_step=f"select_{operation}")
        choices=[]
        for uuid,record in sorted(self._plants.items(),key=lambda item:(str(item[1].get("display_name","")),item[0])):
            label=str(record.get("display_name") or uuid)
            placement=record.get("placement")
            if placement: label=f"{label} · {str(placement).title()}"
            choices.append((uuid,label))
        return PlantSelector(operation,tuple(choices))

    def select_edit(self,plant_uuid: str) -> PlacementForm:
        record=self._get(plant_uuid)
        self.state=OptionsFlowState(plant_uuid,int(record["revision"]),None,{},"edit_placement")
        return PlacementForm("edit",plant_uuid)

    def choose_edit_placement(self,placement: str) -> PlantForm:
        uuid=self.state.selected_plant_uuid
        if uuid is None: raise RuntimeError("plant_not_selected")
        record=self._get(uuid)
        return self._placement_form("edit",placement,uuid,int(record["revision"]),record)

    def select_remove(self,plant_uuid: str) -> RemoveConfirmation:
        record=self._get(plant_uuid)
        self.state=OptionsFlowState(plant_uuid,int(record["revision"]),None,{},"confirm_remove")
        return RemoveConfirmation(plant_uuid,str(record.get("display_name") or plant_uuid),int(record["revision"]))

    def stage_input(self,user_input: Mapping[str,Any]) -> None:
        self.state.pending_form_input=dict(user_input)

    def cancel(self) -> OptionsMenu:
        self.state.clear()
        return OptionsMenu()

    def _placement_form(self,operation: str,placement: str,uuid: str | None,revision: int | None,suggestions: Mapping[str,Any]) -> PlantForm:
        if placement not in {"indoor","outdoor"}: raise ValueError("placement")
        self.state.selected_plant_uuid=uuid
        self.state.expected_revision=revision
        self.state.placement=placement
        self.state.current_step=f"{operation}_{placement}"
        fields=COMMON_FIELDS if placement=="indoor" else OUTDOOR_FIELDS
        values={key:value for key,value in suggestions.items() if key in fields}
        values["placement"]=placement
        if placement=="indoor": values.pop("rain_limit_mm",None)
        return PlantForm(operation,placement,fields,uuid,revision,values)

    def _get(self,plant_uuid: str) -> dict[str,Any]:
        try: return self._plants[plant_uuid]
        except KeyError: raise KeyError("plant_not_found") from None
