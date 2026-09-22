from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Mapping
from .config import GlobalSettings, ValidationError

@dataclass(frozen=True, slots=True)
class SetupForm:
    step_id: str
    defaults: dict[str, Any]
    errors: dict[str, str]

@dataclass(frozen=True, slots=True)
class SetupCreated:
    title: str
    unique_id: str
    data: dict[str, Any]
    options: dict[str, Any]

@dataclass(frozen=True, slots=True)
class SetupAborted:
    reason: str

class SetupFlowModel:
    """Pure setup state machine used by the Home Assistant adapter."""
    UNIQUE_ID="plant_helper"
    TITLE="Plant Helper"

    def start(self, *, existing_entry: bool) -> SetupForm | SetupAborted:
        if existing_entry: return SetupAborted("single_instance_allowed")
        return SetupForm("user",{"perenual_access_level":"free","update_interval":300},{})

    def submit(self, user_input: Mapping[str,Any], *, existing_entry: bool) -> SetupForm | SetupCreated | SetupAborted:
        if existing_entry: return SetupAborted("single_instance_allowed")
        try: settings=GlobalSettings.normalize(user_input)
        except ValidationError as err:
            return SetupForm("user",dict(user_input),{err.key:"invalid"})
        return SetupCreated(self.TITLE,self.UNIQUE_ID,{},settings.to_options())
