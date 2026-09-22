from __future__ import annotations
from typing import Any
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers import selector
from homeassistant.core import callback
from .domain.config import GlobalSettings, ValidationError
from .const import *

GLOBAL_SCHEMA=vol.Schema({
    vol.Optional(CONF_LATITUDE): selector.NumberSelector(selector.NumberSelectorConfig(min=-90,max=90,mode=selector.NumberSelectorMode.BOX)),
    vol.Optional(CONF_LONGITUDE): selector.NumberSelector(selector.NumberSelectorConfig(min=-180,max=180,mode=selector.NumberSelectorMode.BOX)),
    vol.Optional(CONF_OZONE_ENTITY): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
    vol.Optional(CONF_PERENUAL_API_KEY): selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)),
    vol.Required(CONF_PERENUAL_ACCESS_LEVEL,default="free"): selector.SelectSelector(selector.SelectSelectorConfig(options=["free","paid"],mode=selector.SelectSelectorMode.DROPDOWN)),
    vol.Optional(CONF_TREFLE_API_KEY): selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)),
    vol.Required(CONF_UPDATE_INTERVAL,default=300): selector.NumberSelector(selector.NumberSelectorConfig(min=60,max=3600,step=30,mode=selector.NumberSelectorMode.BOX)),
})

class PlantHelperConfigFlow(config_entries.ConfigFlow,domain=DOMAIN):
    VERSION=1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        from .options import PlantHelperOptionsFlow
        return PlantHelperOptionsFlow()

    async def async_step_user(self,user_input: dict[str,Any] | None=None) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        errors={}
        if user_input is not None:
            try:
                options=GlobalSettings.normalize(user_input).to_options()
            except ValidationError as err:
                errors[err.key]="invalid"
            except Exception:
                errors["base"]="invalid_global_settings"
            else:
                return self.async_create_entry(title="Plant Helper",data={},options=options)
        schema=GLOBAL_SCHEMA if user_input is None else self.add_suggested_values_to_schema(GLOBAL_SCHEMA,user_input)
        return self.async_show_form(step_id="user",data_schema=schema,errors=errors)

    async def async_step_reconfigure(self,user_input: dict[str,Any] | None=None) -> ConfigFlowResult:
        entry=self._get_reconfigure_entry()
        errors={}
        if user_input is not None:
            try:
                options=GlobalSettings.normalize(user_input).to_options()
            except ValidationError as err:
                errors[err.key]="invalid"
            except Exception:
                errors["base"]="invalid_global_settings"
            else:
                return self.async_update_reload_and_abort(entry,options=options)
        suggestions=entry.options if user_input is None else user_input
        schema=self.add_suggested_values_to_schema(GLOBAL_SCHEMA,suggestions)
        return self.async_show_form(step_id="reconfigure",data_schema=schema,errors=errors)
