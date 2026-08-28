"""Select entities for Juke general-input configuration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .hub import JukeAudioDevice, JukeAudioHub


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one input-type selector for every general Juke input."""
    entry_data = hass.data[DOMAIN][config_entry.entry_id]
    hub: JukeAudioHub = entry_data["hub"]
    coordinator = entry_data["coordinator"]

    input_infos: dict[str, Mapping[str, Any]] = {}
    input_owners: dict[str, JukeAudioDevice] = {}
    for input_id, input_info in getattr(hub, "group_inputs", {}).items():
        if input_info.get("input_class") == 0:
            input_infos[input_id] = input_info

    for juke in getattr(hub, "jukes", {}).values():
        for input_id, input_info in getattr(juke, "inputs", {}).items():
            if input_info.get("input_class") == 0:
                input_infos.setdefault(input_id, input_info)
                input_owners.setdefault(input_id, juke)

    entities = [
        InputTypeSelect(hub, input_owners.get(input_id), coordinator, input_id)
        for input_id in input_infos
    ]
    if entities:
        async_add_entities(entities)


class InputTypeSelect(CoordinatorEntity, SelectEntity):
    """The configured type of one general Juke input."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        hub: JukeAudioHub,
        juke: JukeAudioDevice | None,
        coordinator,
        input_id: str,
    ) -> None:
        """Initialize the general-input type selector."""
        super().__init__(coordinator)
        self._hub = hub
        self._juke = juke
        self._input_id = input_id

    @property
    def unique_id(self) -> str:
        """Return the stable general-input identity."""
        return f"input_type_{self._input_id}"

    @property
    def name(self) -> str:
        """Return the Juke-app type configuration label."""
        input_info = self._current_input_info()
        return f"{input_info.get('name', self._input_id)} Type"

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return the physical Juke device owning this input."""
        return self._juke.device_info if self._juke is not None else None

    @property
    def current_option(self) -> str | None:
        """Return Juke's currently configured input type."""
        input_type = self._current_input_info().get("input_type")
        return input_type if isinstance(input_type, str) else None

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Expose immutable input identity for the bundled control panel."""
        return {
            "juke_entity_role": "input_type",
            "juke_input_id": self._input_id,
        }

    @property
    def options(self) -> list[str]:
        """Return only the input types Juke exposes for this exact input."""
        input_info = self._current_input_info()
        options = [
            option
            for option in input_info.get("available_types", ())
            if isinstance(option, str)
        ]
        current = self.current_option
        if current is not None and current not in options:
            options.insert(0, current)
        return list(dict.fromkeys(options))

    async def async_select_option(self, option: str) -> None:
        """Set a supported general-input type without redundant writes."""
        if option not in self.options:
            raise HomeAssistantError(f"Input type is not available: {option}")
        if option == self.current_option:
            return
        await self._hub.set_input_type(self._input_id, option)

    def _current_input_info(self) -> Mapping[str, Any]:
        """Read the coordinator-backed general-input record."""
        input_info = getattr(self._hub, "group_inputs", {}).get(self._input_id)
        if input_info is not None:
            return input_info
        return getattr(self._juke, "inputs", {}).get(self._input_id, {})
