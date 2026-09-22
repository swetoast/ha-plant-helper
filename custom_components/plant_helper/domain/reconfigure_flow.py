from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Mapping
from .config import GlobalSettings, ValidationError

@dataclass(frozen=True,slots=True)
class ReconfigureForm:
    suggestions: dict[str,Any]
    errors: dict[str,str]

@dataclass(frozen=True,slots=True)
class ReconfigureUpdated:
    options: dict[str,Any]
    reload_count: int

class ReconfigureFlowModel:
    def open(self,current_options: Mapping[str,Any]) -> ReconfigureForm:
        try: suggestions=GlobalSettings.normalize(current_options).to_options()
        except ValidationError:
            suggestions={"perenual_access_level":"free","update_interval":300}
        return ReconfigureForm(suggestions,{})

    def submit(self,user_input: Mapping[str,Any],current_options: Mapping[str,Any]) -> ReconfigureForm | ReconfigureUpdated:
        try: options=GlobalSettings.normalize(user_input).to_options()
        except ValidationError as err:
            return ReconfigureForm(dict(user_input),{err.key:"invalid"})
        except Exception:
            return ReconfigureForm(dict(user_input),{"base":"invalid_global_settings"})
        return ReconfigureUpdated(options,1)
