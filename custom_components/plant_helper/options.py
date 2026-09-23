from __future__ import annotations
from typing import Any
import logging
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers import selector
from .domain.add_plant import AddPlantError,AddPlantHooks,async_add_plant
from .domain.edit_plant import EditPlantError,EditPlantHooks,async_edit_plant
from .domain.remove_plant import RemovePlantError

_LOGGER=logging.getLogger(__name__)

MENU_OPTIONS=("add","edit","remove")

PLACEMENT_SCHEMA=vol.Schema({vol.Required("placement"): selector.SelectSelector(selector.SelectSelectorConfig(options=["indoor","outdoor"]))})

def plant_schema(placement: str) -> vol.Schema:
    schema={
        vol.Required("display_name"): selector.TextSelector(),
        vol.Required("soil_moisture"): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor",device_class="moisture")),
        vol.Optional("soil_temperature"): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor",device_class="temperature")),
        vol.Optional("humidity_sensor"): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor",device_class="humidity")),
        vol.Optional("lux"): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor",device_class="illuminance")),
        vol.Optional("battery"): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
        vol.Required("profile",default="balanced"): selector.SelectSelector(selector.SelectSelectorConfig(options=["dry","balanced","moist","custom"])),
        vol.Optional("custom_multiplier"): selector.NumberSelector(selector.NumberSelectorConfig(min=0.25,max=4.0,mode=selector.NumberSelectorMode.BOX)),
    }
    if placement=="outdoor":
        schema[vol.Required("rain_limit_mm")]=selector.NumberSelector(selector.NumberSelectorConfig(min=0,max=1000,mode=selector.NumberSelectorMode.BOX))
    return vol.Schema(schema)

class PlantHelperOptionsFlow(config_entries.OptionsFlow):
    def __init__(self) -> None:
        self._selected_plant_uuid: str | None=None
        self._expected_revision: int | None=None
        self._placement: str | None=None
        self._pending_form_input: dict[str,Any]={}
        self._species_candidates: list[dict[str,Any]]=[]
        self._species_return_step: str | None=None

    async def async_step_init(self,user_input: dict[str,Any] | None=None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="init",menu_options=list(MENU_OPTIONS))

    async def async_step_add(self,user_input: dict[str,Any] | None=None) -> ConfigFlowResult:
        if user_input is not None:
            self._placement=user_input["placement"]
            return await self.async_step_add_plant()
        return self.async_show_form(step_id="add",data_schema=PLACEMENT_SCHEMA)

    async def async_step_add_plant(self,user_input: dict[str,Any] | None=None) -> ConfigFlowResult:
        errors={}
        if user_input is not None:
            self._pending_form_input=dict(user_input)
            common_name=str(user_input.get("display_name","")).strip()
            self._pending_form_input["species"]=common_name or None
            if common_name:
                result=await self._async_resolve_species(common_name,"add")
                if result is not None:return result
            return await self._async_finish_add()
        schema=self.add_suggested_values_to_schema(plant_schema(self._placement or "indoor"),self._pending_form_input)
        return self.async_show_form(step_id="add_plant",data_schema=schema,errors=errors)

    async def _async_resolve_species(self,query: str,return_step: str) -> ConfigFlowResult | None:
        runtime=self.config_entry.runtime_data
        chain=runtime.species_enrichment
        if chain is None:return None
        try:candidates=await chain.discover(query)
        except Exception:
            _LOGGER.exception("Failed to resolve common plant name")
            return None
        if not candidates:return None
        self._species_candidates=candidates
        self._species_return_step=return_step
        if len(candidates)==1:
            self._pending_form_input["species"]=str(candidates[0].get("scientific_name") or query)
            return None
        return await self.async_step_select_species()

    async def async_step_select_species(self,user_input: dict[str,Any] | None=None) -> ConfigFlowResult:
        if user_input is not None:
            index=int(user_input["candidate"])
            if index<0 or index>=len(self._species_candidates):
                return self.async_abort(reason="plant_not_found")
            selected=self._species_candidates[index]
            self._pending_form_input["species"]=str(selected.get("scientific_name") or self._pending_form_input.get("species",''))
            if self._species_return_step=="add":return await self._async_finish_add()
            return self.async_abort(reason="plant_not_found")
        options=[]
        for index,candidate in enumerate(self._species_candidates):
            scientific=str(candidate.get("scientific_name") or "Unknown species")
            common=str(candidate.get("common_name") or "No common name")
            matched=str(candidate.get("matched_term") or common)
            options.append({"value":str(index),"label":f"{common} · {scientific} · matched: {matched}"})
        return self.async_show_form(
            step_id="select_species",
            data_schema=vol.Schema({vol.Required("candidate"):selector.SelectSelector(selector.SelectSelectorConfig(options=options,mode=selector.SelectSelectorMode.DROPDOWN))}),
        )

    async def _async_finish_add(self) -> ConfigFlowResult:
        runtime=self.config_entry.runtime_data
        hooks=AddPlantHooks(
            register_listeners=runtime.register_listeners,
            request_entities=self._async_request_entities,
            evaluate=runtime.evaluate,
            schedule_enrichment=runtime.schedule_enrichment,
            schedule_reconciliation=runtime.schedule_reconciliation,
        )
        try:
            await async_add_plant(
                raw=self._pending_form_input,
                placement=self._placement or "indoor",
                storage=runtime.require_storage(),
                runtime=runtime.plants,
                moisture_reader=lambda entity_id: self.hass.states.get(entity_id).state if self.hass.states.get(entity_id) else None,
                hooks=hooks,
            )
        except AddPlantError as err:
            return self.async_show_form(step_id="add_plant",data_schema=self.add_suggested_values_to_schema(plant_schema(self._placement or "indoor"),self._pending_form_input),errors={err.key:"invalid"})
        except Exception:
            _LOGGER.exception("Failed to add plant")
            return self.async_show_form(step_id="add_plant",data_schema=self.add_suggested_values_to_schema(plant_schema(self._placement or "indoor"),self._pending_form_input),errors={"base":"cannot_save_plant"})
        self._clear_transient()
        return self.async_create_entry(title="",data=dict(self.config_entry.options))

    async def _async_request_entities(self, plant_uuid: str) -> None:
        """Ask every loaded entity platform to reconcile this committed plant."""
        runtime = self.config_entry.runtime_data
        for platform in ("sensor", "binary_sensor"):
            callback = runtime.platform_callbacks.get(platform)
            if callback is not None:
                callback(plant_uuid)

    def _clear_transient(self) -> None:
        self._selected_plant_uuid=None
        self._expected_revision=None
        self._placement=None
        self._pending_form_input.clear()

    async def async_step_edit(self,user_input: dict[str,Any] | None=None) -> ConfigFlowResult:
        runtime=self.config_entry.runtime_data
        plants=runtime.plants.plants
        if user_input is not None:
            self._selected_plant_uuid=user_input["plant_uuid"]
            selected=plants.get(self._selected_plant_uuid)
            if selected is None:
                return self.async_abort(reason="plant_not_found")
            self._expected_revision=int(selected.config["revision"])
            return await self.async_step_edit_placement()
        options=[{"value":uuid,"label":f"{plant.config.get('display_name',uuid)} · {str(plant.config.get('placement','')).title()}"} for uuid,plant in sorted(plants.items())]
        schema=vol.Schema({vol.Required("plant_uuid"): selector.SelectSelector(selector.SelectSelectorConfig(options=options))})
        return self.async_show_form(step_id="edit",data_schema=schema)

    async def async_step_edit_placement(self,user_input: dict[str,Any] | None=None) -> ConfigFlowResult:
        if user_input is not None:
            self._placement=user_input["placement"]
            return await self.async_step_edit_plant()
        return self.async_show_form(step_id="edit_placement",data_schema=PLACEMENT_SCHEMA)

    async def async_step_edit_plant(self,user_input: dict[str,Any] | None=None) -> ConfigFlowResult:
        runtime=self.config_entry.runtime_data
        uuid=self._selected_plant_uuid
        if uuid is None or self._expected_revision is None:
            return self.async_abort(reason="plant_not_found")
        plant=runtime.plants.plants.get(uuid)
        if plant is None:
            return self.async_abort(reason="plant_not_found")
        errors={}
        if user_input is not None:
            self._pending_form_input=dict(user_input)
            hooks=EditPlantHooks(
                replace_listeners=runtime.replace_listeners,
                evaluate=runtime.evaluate,
                handle_placement_change=runtime.handle_placement_change,
                handle_species_change=runtime.handle_species_change,
                schedule_enrichment=runtime.schedule_enrichment,
                schedule_reconciliation=runtime.schedule_reconciliation,
            )
            try:
                await async_edit_plant(
                    plant_uuid=uuid,
                    expected_revision=self._expected_revision,
                    raw=user_input,
                    placement=self._placement or plant.config["placement"],
                    storage=runtime.require_storage(),
                    runtime=runtime.plants,
                    moisture_reader=lambda entity_id: self.hass.states.get(entity_id).state if self.hass.states.get(entity_id) else None,
                    destination_baseline_complete=bool(runtime.destination_baseline_complete(uuid,self._placement or plant.config["placement"])),
                    hooks=hooks,
                )
            except EditPlantError as err:
                errors["base" if err.key=="plant_changed" else err.key]=err.key
            except Exception:
                errors["base"]="cannot_save_plant"
            else:
                self._clear_transient()
                return self.async_create_entry(title="",data=dict(self.config_entry.options))
        suggestions={key:value for key,value in plant.config.items() if key not in {"plant_uuid","revision","placement"}}
        if user_input is not None: suggestions=user_input
        schema=self.add_suggested_values_to_schema(plant_schema(self._placement or plant.config["placement"]),suggestions)
        return self.async_show_form(step_id="edit_plant",data_schema=schema,errors=errors)

    async def async_step_remove(self,user_input: dict[str,Any] | None=None) -> ConfigFlowResult:
        runtime=self.config_entry.runtime_data; plants=runtime.plants.plants
        if user_input is not None:
            self._selected_plant_uuid=user_input["plant_uuid"]
            plant=plants.get(self._selected_plant_uuid)
            if plant is None:return self.async_abort(reason="plant_not_found")
            self._expected_revision=int(plant.config["revision"])
            return await self.async_step_confirm_remove()
        if not plants:
            return self.async_abort(reason="no_plants")
        options=[{"value":u,"label":f"{p.config.get('display_name',u)} · {str(p.config.get('placement','')).title()}"} for u,p in sorted(plants.items())]
        return self.async_show_form(step_id="remove",data_schema=vol.Schema({vol.Required("plant_uuid"):selector.SelectSelector(selector.SelectSelectorConfig(options=options))}))

    async def async_step_confirm_remove(self,user_input: dict[str,Any] | None=None) -> ConfigFlowResult:
        runtime=self.config_entry.runtime_data; uuid=self._selected_plant_uuid
        if uuid is None or self._expected_revision is None:return self.async_abort(reason="plant_not_found")
        errors={}
        if user_input is not None:
            if not user_input.get("confirm", False):
                errors["base"] = "confirmation_required"
            else:
                try:
                    await runtime.remove_plant(uuid, self._expected_revision)
                except RemovePlantError as err:
                    errors["base"] = err.key
                except Exception:
                    _LOGGER.exception("Failed to remove plant before durable deletion")
                    errors["base"] = "cannot_remove_plant"
                else:
                    self._clear_transient()
                    return self.async_create_entry(title="", data=dict(self.config_entry.options))
        return self.async_show_form(step_id="confirm_remove",data_schema=vol.Schema({vol.Required("confirm",default=False):bool}),errors=errors)
