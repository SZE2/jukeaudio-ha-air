"""Config flow for Juke Audio integration."""
from __future__ import annotations

import ipaddress
import json
import re
from collections.abc import Mapping

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_USERNAME, CONF_PASSWORD,CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError

from .const import CONF_AIRPLAY_TARGETS, DOMAIN, LOGGER
from .airplay import AirPlayMappingError, dump_airplay_targets, load_airplay_targets
from .hub import JukeAudioHub
from jukeaudio.exceptions import AuthenticationException, UnexpectedException

# TODO adjust the data schema to the data that you need
STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST, default="juke.local"): str,
        vol.Required(CONF_USERNAME, default="Admin"): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_SCAN_INTERVAL, default=30): int
    }
)


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject ambiguous target records before mapping validation."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate target mapping key")
        result[key] = value
    return result


def host_valid(host):
    """Return True if hostname or IP address is valid."""
    try:
        if ipaddress.ip_address(host).version == (4 or 6):
            return True
    except ValueError:
        disallowed = re.compile(r"[^a-zA-Z\d\-]")
        return all(x and not disallowed.search(x) for x in host.split("."))


async def validate_input(hass: HomeAssistant, data: dict[str, Any]):
    """Validate the user input allows us to connect."""

    if not host_valid(data[CONF_HOST]):
        raise CannotConnect
    
    if CONF_SCAN_INTERVAL in data:
        try:
            update_interval = int(data[CONF_SCAN_INTERVAL])
        except ValueError:
            raise InvalidUpdateInterval(ValueError)

    hub = JukeAudioHub(hass, data[CONF_HOST], data[CONF_USERNAME], data[CONF_PASSWORD])

    if not await hub.verify_connection():
        raise CannotConnect

    LOGGER.debug("Successfully reached the Juke amplifier on the network")
    return await hub.get_devices()


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Juke Audio."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        """Return the options flow for integrated RAOP configuration."""
        return OptionsFlowHandler(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except CannotConnect:
                LOGGER.exception("Failed to reach Juke amplifier on the network")
                errors["base"] = "cannot_connect"
            except UnexpectedException:
                LOGGER.exception("Unknown exception")
                errors["base"] = "unknown"
            except AuthenticationException:
                LOGGER.exception("Failed to authenticate")
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                LOGGER.debug("Juke devices: %s. Registering with %s", info, info[0])
                return self.async_create_entry(title=info[0], data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_reauth(self, user_input: dict[str, Any]) -> FlowResult:
        """Perform reauth upon an authentication error."""
        self.reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )

        hub: JukeAudioHub = self.hass.data[DOMAIN][self.reauth_entry.entry_id]["hub"]
        
        await hub.get_connection_info()
        LOGGER.debug("Successfully connected to the Juke amplifier")

        self.hass.config_entries.async_update_entry(self.reauth_entry, data=user_input)
        await self.hass.config_entries.async_reload(self.reauth_entry.entry_id)

        return self.async_abort(reason="reauth_successful")


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""

class InvalidUpdateInterval(HomeAssistantError):
    """Error to indicate incorrect update interval setting"""


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Configure explicit in-process RAOP target mappings."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    def _schema(self) -> vol.Schema:
        """Build the mapping form from the current explicit targets."""
        options = self._config_entry.options
        target_mapping = options.get(CONF_AIRPLAY_TARGETS, {})
        if isinstance(target_mapping, Mapping):
            targets_default = json.dumps(target_mapping, sort_keys=True)
        else:
            targets_default = "{}"
        return vol.Schema(
            {
                vol.Required(CONF_AIRPLAY_TARGETS, default=targets_default): str,
            }
        )

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle integrated RAOP options."""
        errors: dict[str, str] = {}
        target_mapping = None
        if user_input is not None:
            try:
                decoded_mapping = json.loads(
                    user_input.get(CONF_AIRPLAY_TARGETS, ""),
                    object_pairs_hook=_reject_duplicate_json_keys,
                )
                targets = load_airplay_targets(decoded_mapping)
                target_mapping = dump_airplay_targets(targets)
            except (AirPlayMappingError, TypeError, ValueError, json.JSONDecodeError):
                errors[CONF_AIRPLAY_TARGETS] = "invalid_target_mapping"

            if not errors:
                options = {
                    key: value
                    for key, value in self._config_entry.options.items()
                    if not (isinstance(key, str) and key.startswith("helper_"))
                }
                options[CONF_AIRPLAY_TARGETS] = target_mapping
                return self.async_create_entry(
                    title="",
                    data=options,
                )

        return self.async_show_form(
            step_id="init", data_schema=self._schema(), errors=errors
        )
