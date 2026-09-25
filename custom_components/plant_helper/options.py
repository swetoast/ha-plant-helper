from __future__ import annotations
from typing import Any
import logging
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers import selector
from .domain.add_plant import AddPlantError,AddPlantHooks,async_add_plant
from .domain.edit_plant import EditPlantError,EditPlantHooks,async_edit_plant
from .domain.enrichment import ProviderError,describe_candidate,is_exact_candidate,is_restricted,rank_candidates
from .domain.remove_plant import RemovePlantError

_LOGGER=logging.getLogger(__name__)

MENU_OPTIONS=("add","edit","species","remove")

# Per-provider species matching: one step per configured provider, in order.
PROVIDER_ORDER=("inaturalist","trefle","perenual")
SKIP="skip"
MAX_CANDIDATES=10
MAX_QUERIES=3
SKIP_LABELS={
    "inaturalist":"None of these - no species",
    "trefle":"Skip Trefle",
    "perenual":"Skip Perenual",
}

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
        self._flow_mode: str="add"
        self._query: str=""
        self._names: list[str]=[]
        self._sources: dict[str,Any]={}
        self._candidates: dict[str,list[dict[str,Any]]]={}

    async def async_step_init(self,user_input: dict[str,Any] | None=None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="init",menu_options=list(MENU_OPTIONS))

    async def async_step_add(self,user_input: dict[str,Any] | None=None) -> ConfigFlowResult:
        if user_input is not None:
            self._placement=user_input["placement"]
            return await self.async_step_add_plant()
        return self.async_show_form(step_id="add",data_schema=PLACEMENT_SCHEMA)

    async def async_step_add_plant(self,user_input: dict[str,Any] | None=None) -> ConfigFlowResult:
        if user_input is not None:
            self._pending_form_input=dict(user_input)
            self._flow_mode="add"
            return await self._async_start_matching(str(user_input.get("display_name","")).strip())
        schema=self.add_suggested_values_to_schema(plant_schema(self._placement or "indoor"),self._pending_form_input)
        return self.async_show_form(step_id="add_plant",data_schema=schema)

    # ---- per-provider species matching ------------------------------------
    # Each configured provider gets its own step listing its records for this
    # plant, with Skip. The chosen record IDs are stored on the plant, and
    # enrichment fetches exactly those records; nothing is re-matched later.

    async def _async_start_matching(self,query: str) -> ConfigFlowResult:
        self._query=query
        self._names=[query] if query else []
        self._sources={}
        self._candidates={}
        return await self._async_provider_step(PROVIDER_ORDER[0])

    def _adapter(self,provider: str) -> Any:
        return self.config_entry.runtime_data.provider_adapters.get(provider)

    async def _async_provider_step(self,provider: str | None) -> ConfigFlowResult:
        """Show the next configured provider's step, or finish matching."""
        remaining=PROVIDER_ORDER[PROVIDER_ORDER.index(provider):] if provider else ()
        for name in remaining:
            if self._adapter(name) is not None and self._names:
                return await getattr(self,f"async_step_species_{name}")()
        return await self._async_finish_matching()

    async def _async_search(self,provider: str) -> tuple[list[dict[str,Any]],str]:
        """Search one provider with the names known so far; (candidates, status)."""
        adapter=self._adapter(provider)
        queries=[self._query] if provider=="inaturalist" else self._names[:MAX_QUERIES]
        found: list[dict[str,Any]]=[]
        for query in queries:
            try:
                results=await adapter.search(query)
            except ProviderError as err:
                message={
                    "auth":"The API key was rejected.",
                    "rate":"Rate limited right now; try again in a minute.",
                    "plan":"Your plan does not include this search.",
                }.get(err.kind,"The provider could not be reached.")
                return self._rank(provider,found),message
            except Exception:
                _LOGGER.debug("Species search failed for %s",provider,exc_info=True)
                return self._rank(provider,found),"The provider could not be reached."
            for item in results:
                if provider=="inaturalist":
                    item=dict(item,id=item.get("provider_id"))
                found.append(item)
            if provider!="inaturalist" and any(is_exact_candidate(c,self._names) for c in found):
                break  # a confirmed match: spare the provider's daily quota
        ranked=self._rank(provider,found)
        return ranked,"" if ranked else "No matching records were found."

    def _rank(self,provider: str,found: list[dict[str,Any]]) -> list[dict[str,Any]]:
        if provider=="inaturalist":
            return [c for c in found if c.get("id") is not None][:MAX_CANDIDATES]
        return rank_candidates(found,self._names)[:MAX_CANDIDATES]

    async def _async_species_step(self,provider: str,user_input: dict[str,Any] | None) -> ConfigFlowResult:
        following=PROVIDER_ORDER[PROVIDER_ORDER.index(provider)+1] if provider!=PROVIDER_ORDER[-1] else None
        if user_input is not None:
            choice=str(user_input.get("candidate",SKIP))
            picked=next((c for c in self._candidates.get(provider,[]) if str(c.get("id"))==choice),None)
            if picked is None:
                self._sources[provider]=SKIP
            else:
                self._record_choice(provider,picked)
            return await self._async_provider_step(following)
        candidates,status=await self._async_search(provider)
        runtime=self.config_entry.runtime_data
        if provider=="perenual":
            candidates,status=self._perenual_tier(candidates,status,runtime.perenual_free)
        self._candidates[provider]=candidates
        options=[
            {"value":str(c["id"]),"label":describe_candidate(provider,c,perenual_free=runtime.perenual_free)}
            for c in candidates
        ]
        options.append({"value":SKIP,"label":SKIP_LABELS[provider]})
        default=SKIP
        top=candidates[0] if candidates else None
        if top is not None and (provider=="inaturalist" or is_exact_candidate(top,self._names)):
            default=str(top["id"])
        if top is not None and provider=="perenual" and is_restricted(top,perenual_free=runtime.perenual_free):
            default=SKIP  # the record exists but this key cannot open its care data
        schema=vol.Schema({vol.Required("candidate",default=default):selector.SelectSelector(
            selector.SelectSelectorConfig(options=options,mode=selector.SelectSelectorMode.LIST))})
        return self.async_show_form(
            step_id=f"species_{provider}",
            data_schema=schema,
            description_placeholders={"query":self._names[0] if self._names else self._query,"status":status},
        )

    @staticmethod
    def _perenual_tier(candidates: list[dict[str,Any]],status: str,free: bool) -> tuple[list[dict[str,Any]],str]:
        """Free plan: only records the key can open. Paid: all, warn if any are locked."""
        locked=[c for c in candidates if is_restricted(c,perenual_free=free)]
        if free:
            opened=[c for c in candidates if c not in locked]
            if locked and not opened:
                return [],"Perenual lists this plant, but only paid plans include its care data."
            if locked:
                return opened,f"{len(locked)} paid-only record(s) hidden."
            return opened,status
        if locked:
            return candidates,"Some records came back locked, so this key looks like a free plan. Check the Perenual plan setting."
        return candidates,status

    def _record_choice(self,provider: str,picked: dict[str,Any]) -> None:
        name=str(picked.get("scientific_name") or "").strip()
        entry={"id":picked.get("id"),"name":name or None}
        if provider=="inaturalist":
            entry["common_name"]=picked.get("common_name")
            entry["image_url"]=picked.get("image_url")
        self._sources[provider]={key:value for key,value in entry.items() if value is not None}
        # Later providers match the chosen record's name and synonyms first.
        chosen=[name,*[str(s) for s in picked.get("synonyms") or [] if s],picked.get("common_name")]
        self._names=list(dict.fromkeys([str(n) for n in chosen if n]+self._names))

    async def async_step_species_inaturalist(self,user_input: dict[str,Any] | None=None) -> ConfigFlowResult:
        return await self._async_species_step("inaturalist",user_input)

    async def async_step_species_trefle(self,user_input: dict[str,Any] | None=None) -> ConfigFlowResult:
        return await self._async_species_step("trefle",user_input)

    async def async_step_species_perenual(self,user_input: dict[str,Any] | None=None) -> ConfigFlowResult:
        return await self._async_species_step("perenual",user_input)

    async def _async_finish_matching(self) -> ConfigFlowResult:
        species=None
        for provider in ("trefle","inaturalist","perenual"):  # accepted name first
            choice=self._sources.get(provider)
            if isinstance(choice,dict) and choice.get("name"):
                species=choice["name"]
                break
        self._pending_form_input["species"]=species
        self._pending_form_input["species_sources"]=dict(self._sources) or None
        if self._flow_mode=="rematch":
            return await self._async_finish_rematch()
        return await self._async_finish_add()

    async def async_step_species(self,user_input: dict[str,Any] | None=None) -> ConfigFlowResult:
        """Re-match an existing plant's species data, provider by provider."""
        plants=self.config_entry.runtime_data.plants.plants
        if not plants:
            return self.async_abort(reason="no_plants")
        if user_input is not None:
            uuid=user_input["plant_uuid"]
            plant=plants.get(uuid)
            if plant is None:
                return self.async_abort(reason="plant_not_found")
            self._selected_plant_uuid=uuid
            self._expected_revision=int(plant.config["revision"])
            self._placement=str(plant.config["placement"])
            self._pending_form_input={k:v for k,v in plant.config.items() if k not in {"plant_uuid","revision"}}
            self._flow_mode="rematch"
            query=str(user_input.get("search") or plant.config.get("display_name") or "").strip()
            return await self._async_start_matching(query)
        options=[{"value":u,"label":f"{p.config.get('display_name',u)} - {p.config.get('species') or 'no species'}"} for u,p in sorted(plants.items())]
        schema=vol.Schema({
            vol.Required("plant_uuid"):selector.SelectSelector(selector.SelectSelectorConfig(options=options)),
            vol.Optional("search"):selector.TextSelector(),
        })
        return self.async_show_form(step_id="species",data_schema=schema)

    async def _async_finish_rematch(self) -> ConfigFlowResult:
        uuid=self._selected_plant_uuid
        if uuid is None or self._expected_revision is None:
            return self.async_abort(reason="plant_not_found")
        error=await self._async_save_edit(uuid,dict(self._pending_form_input),self._placement)
        if error is not None:
            return self.async_abort(reason=error if error=="plant_changed" else "cannot_save_plant")
        self._clear_transient()
        return self.async_create_entry(title="",data=dict(self.config_entry.options))

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
            return self.async_show_form(step_id="add_plant",data_schema=self.add_suggested_values_to_schema(plant_schema(self._placement or "indoor"),self._pending_form_input),errors={"base":err.key})
        except Exception:
            _LOGGER.exception("Failed to add plant")
            return self.async_show_form(step_id="add_plant",data_schema=self.add_suggested_values_to_schema(plant_schema(self._placement or "indoor"),self._pending_form_input),errors={"base":"cannot_save_plant"})
        self._clear_transient()
        return self.async_create_entry(title="",data=dict(self.config_entry.options))

    async def _async_request_entities(self, plant_uuid: str) -> None:
        """Ask every loaded entity platform to reconcile this committed plant."""
        runtime = self.config_entry.runtime_data
        for platform in ("sensor", "binary_sensor", "image"):
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
        options=[{"value":uuid,"label":f"{plant.config.get('display_name',uuid)} - {str(plant.config.get('placement','')).title()}"} for uuid,plant in sorted(plants.items())]
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
            raw=dict(user_input)
            if not raw.get("species") and plant.config.get("species"):
                raw["species"]=plant.config.get("species")
            if not raw.get("species_sources") and plant.config.get("species_sources"):
                raw["species_sources"]=plant.config.get("species_sources")
            error=await self._async_save_edit(uuid,raw,self._placement or plant.config["placement"])
            if error is not None:
                errors["base"]=error
            else:
                self._clear_transient()
                return self.async_create_entry(title="",data=dict(self.config_entry.options))
        suggestions={key:value for key,value in plant.config.items() if key not in {"plant_uuid","revision","placement"}}
        if user_input is not None: suggestions=user_input
        schema=self.add_suggested_values_to_schema(plant_schema(self._placement or plant.config["placement"]),suggestions)
        return self.async_show_form(step_id="edit_plant",data_schema=schema,errors=errors)

    async def _async_save_edit(self,uuid: str,raw: dict[str,Any],placement: str | None) -> str | None:
        """Persist an edited plant through the domain edit path; error key or None."""
        runtime=self.config_entry.runtime_data
        plant=runtime.plants.plants.get(uuid)
        if plant is None or self._expected_revision is None:
            return "plant_changed"
        target=placement or plant.config["placement"]
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
                raw=raw,
                placement=target,
                storage=runtime.require_storage(),
                runtime=runtime.plants,
                moisture_reader=lambda entity_id: self.hass.states.get(entity_id).state if self.hass.states.get(entity_id) else None,
                destination_baseline_complete=bool(runtime.destination_baseline_complete(uuid,target)),
                hooks=hooks,
            )
        except EditPlantError as err:
            return err.key
        except Exception:
            _LOGGER.exception("Failed to save plant")
            return "cannot_save_plant"
        return None

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
        options=[{"value":u,"label":f"{p.config.get('display_name',u)} - {str(p.config.get('placement','')).title()}"} for u,p in sorted(plants.items())]
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
