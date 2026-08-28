"""Switches for non-destructive Juke input-to-zone routing."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.components.switch import SwitchEntity

from .const import DOMAIN
from .hub import JukeAudioHub, JukeAudioDevice


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one switch for every general-input/zone pair."""
    entry_data = hass.data[DOMAIN][config_entry.entry_id]
    hub: JukeAudioHub = entry_data["hub"]
    coordinator = entry_data["coordinator"]

    input_infos: dict[str, Mapping[str, Any]] = {}
    input_owners: dict[str, JukeAudioDevice] = {}
    for input_id, input_info in getattr(hub, "group_inputs", {}).items():
        if input_info.get("input_class") == 0:
            input_infos[input_id] = input_info

    zone_owners: dict[str, JukeAudioDevice] = {}
    for juke in getattr(hub, "jukes", {}).values():
        for zone_id in juke.zones:
            zone_owners.setdefault(zone_id, juke)
        for input_id, input_info in getattr(juke, "inputs", {}).items():
            if input_info.get("input_class") == 0:
                input_infos.setdefault(input_id, input_info)
                input_owners.setdefault(input_id, juke)

    entities = [
        InputEnabledSwitch(
            hub,
            input_owners.get(input_id),
            coordinator,
            input_id,
        )
        for input_id in input_infos
    ] + [
        InputZoneSwitch(
            hub,
            zone_owners[zone_id],
            coordinator,
            config_entry,
            input_id,
            zone_id,
        )
        for input_id in input_infos
        for zone_id in zone_owners
    ]

    if entities:
        async_add_entities(entities)


class InputEnabledSwitch(CoordinatorEntity, SwitchEntity):
    """A general input's Juke-app enable toggle."""

    _attr_has_entity_name = True

    def __init__(
        self,
        hub: JukeAudioHub,
        juke: JukeAudioDevice | None,
        coordinator,
        input_id: str,
    ) -> None:
        """Initialize an input-enable switch."""
        super().__init__(coordinator)
        self._hub = hub
        self._juke = juke
        self._input_id = input_id

    @property
    def unique_id(self) -> str:
        """Return the stable general-input identity."""
        return f"input_enable_{self._input_id}"

    @property
    def name(self) -> str:
        """Return the Juke-app input enable label."""
        input_info = self._current_input_info()
        return f"{input_info.get('name', self._input_id)} Enabled"

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return the physical Juke device owning this input."""
        return self._juke.device_info if self._juke is not None else None

    @property
    def is_on(self) -> bool:
        """Return Juke's current general-input enablement state."""
        return bool(self._current_input_info().get("enabled", True))

    async def async_turn_on(self) -> None:
        """Enable the general input."""
        await self._hub.set_input_enabled(self._input_id, True)

    async def async_turn_off(self) -> None:
        """Disable the general input."""
        await self._hub.set_input_enabled(self._input_id, False)

    def _current_input_info(self) -> Mapping[str, Any]:
        """Read the coordinator-backed general-input record."""
        input_info = getattr(self._hub, "group_inputs", {}).get(self._input_id)
        if input_info is not None:
            return input_info
        return getattr(self._juke, "inputs", {}).get(self._input_id, {})


class InputZoneSwitch(CoordinatorEntity, SwitchEntity):
    """A cached, non-destructive general-input-to-zone mapping switch."""

    _attr_has_entity_name = True

    def __init__(
        self,
        hub: JukeAudioHub,
        juke: JukeAudioDevice,
        coordinator,
        config_entry: ConfigEntry,
        input_id: str,
        zone_id: str,
    ) -> None:
        """Initialize a routing switch."""
        super().__init__(coordinator)
        self._hub = hub
        self._juke = juke
        self._config_entry = config_entry
        self._input_id = input_id
        self._zone_id = zone_id

    @property
    def unique_id(self) -> str:
        """Return the stable routing-pair identifier."""
        return f"route_{self._input_id}_{self._zone_id}"

    @property
    def name(self) -> str:
        """Return the input-to-zone display name."""
        input_info = self._current_input_info()
        zone_info = self._juke.zones[self._zone_id]
        return f"{input_info.get('name', self._input_id)} to {zone_info.get('name', self._zone_id)}"

    @property
    def device_info(self) -> DeviceInfo:
        """Return the physical Juke device for this zone."""
        return self._juke.device_info

    @property
    def is_on(self) -> bool:
        """Return whether the cached input mapping includes this zone."""
        input_info = self._current_input_info()
        return self._zone_id in _zone_ids(input_info.get("zones", ()))

    async def async_turn_on(self) -> None:
        """Add this zone to the input without replacing other mappings."""
        await self._hub.add_input_zone(self._input_id, self._zone_id)

    async def async_turn_off(self) -> None:
        """Remove this zone from the input without replacing other mappings."""
        await self._hub.remove_input_zone(self._input_id, self._zone_id)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Write the state after the coordinator refreshes its cache."""
        self.async_write_ha_state()

    def _current_input_info(self) -> Mapping[str, Any]:
        """Read the current input record from the coordinator-backed hub cache."""
        input_info = getattr(self._hub, "group_inputs", {}).get(self._input_id)
        if input_info is not None:
            return input_info

        for juke in getattr(self._hub, "jukes", {}).values():
            input_info = getattr(juke, "inputs", {}).get(self._input_id)
            if input_info is not None:
                return input_info

        return {}


def _zone_ids(zones: Any) -> set[str]:
    """Normalize cached InputInfo.zones values to zone identifiers."""
    if zones is None:
        return set()
    if isinstance(zones, str):
        zones = (zones,)
    elif isinstance(zones, Mapping):
        if "zone_ids" in zones:
            zones = zones["zone_ids"]
        elif "zones" in zones:
            zones = zones["zones"]
        else:
            zones = zones.keys()

    zone_ids: set[str] = set()
    for zone in zones:
        if isinstance(zone, str):
            zone_ids.add(zone)
        elif isinstance(zone, Mapping):
            zone_id = zone.get("zone_id", zone.get("id"))
            if isinstance(zone_id, str):
                zone_ids.add(zone_id)
    return zone_ids
