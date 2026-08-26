"""Automation-safe Juke input-to-zone routing services."""

from __future__ import annotations

from collections.abc import Mapping
from functools import partial
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN

SERVICE_SET_INPUT_ZONES = "set_input_zones"
SERVICE_ADD_INPUT_ZONE = "add_input_zone"
SERVICE_REMOVE_INPUT_ZONE = "remove_input_zone"

_INPUT_ID = "input_id"
_ZONE_ID = "zone_id"
_ZONE_IDS = "zone_ids"
_SERVICES_REGISTERED = "_routing_services_registered"

_TEXT = vol.All(str, vol.Length(min=1))
_SERVICE_SCHEMAS = {
    SERVICE_SET_INPUT_ZONES: vol.Schema(
        {
            vol.Required(_INPUT_ID): _TEXT,
            # An empty list is valid: it removes every route for this input.
            vol.Required(_ZONE_IDS): vol.All([_TEXT]),
        }
    ),
    SERVICE_ADD_INPUT_ZONE: vol.Schema(
        {vol.Required(_INPUT_ID): _TEXT, vol.Required(_ZONE_ID): _TEXT}
    ),
    SERVICE_REMOVE_INPUT_ZONE: vol.Schema(
        {vol.Required(_INPUT_ID): _TEXT, vol.Required(_ZONE_ID): _TEXT}
    ),
}


def _hubs(hass: HomeAssistant | None) -> list[Any]:
    """Return configured hubs without treating service metadata as an entry."""
    if hass is None:
        return []

    domain_data = getattr(hass, "data", {}).get(DOMAIN, {})
    result = []
    for entry_data in domain_data.values():
        if not isinstance(entry_data, Mapping):
            continue
        hub = entry_data.get("hub")
        if hub is not None and all(hub is not current for current in result):
            result.append(hub)
    return result


def _records(mapping: Any, id_field: str):
    """Yield immutable IDs and metadata from a Juke mapping."""
    if not isinstance(mapping, Mapping):
        return
    for key, value in mapping.items():
        if not isinstance(value, Mapping):
            continue
        immutable_id = value.get(id_field, key)
        if isinstance(immutable_id, str) and immutable_id:
            yield immutable_id, value, key


def _input_records(hub: Any):
    """Yield all input records visible on a hub."""
    mappings = [getattr(hub, "group_inputs", None), getattr(hub, "inputs", None)]
    jukes = getattr(hub, "jukes", {})
    if isinstance(jukes, Mapping):
        mappings.extend(getattr(juke, "inputs", None) for juke in jukes.values())

    seen = set()
    for mapping in mappings:
        for immutable_id, info, key in _records(mapping, "input_id"):
            marker = (immutable_id, info.get("input_class"), info.get("name"))
            if marker in seen:
                continue
            seen.add(marker)
            yield immutable_id, info, key


def _zone_records(hub: Any):
    """Yield all zone records visible on a hub."""
    mappings = [getattr(hub, "zones", None)]
    jukes = getattr(hub, "jukes", {})
    if isinstance(jukes, Mapping):
        mappings.extend(getattr(juke, "zones", None) for juke in jukes.values())

    seen = set()
    for mapping in mappings:
        for immutable_id, info, key in _records(mapping, "zone_id"):
            marker = (immutable_id, info.get("name"), info.get("label"))
            if marker in seen:
                continue
            seen.add(marker)
            yield immutable_id, info, key


def _required_text(data: Mapping[str, Any], field: str) -> str:
    """Read a required non-empty service field."""
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise HomeAssistantError(f"Missing {field}")
    return value


def _resolve_input(hass: HomeAssistant | None, identifier: str, hub: Any = None):
    """Resolve an input ID or label to one immutable general-input ID."""
    candidates = [hub] if hub is not None else _hubs(hass)
    matches = []
    for candidate_hub in candidates:
        for immutable_id, info, key in _input_records(candidate_hub):
            if identifier in {immutable_id, key, info.get("name")}:
                matches.append((candidate_hub, immutable_id, info))

    if not matches:
        raise HomeAssistantError(f"Unknown input: {identifier}")
    if any(info.get("input_class") != 0 for _, _, info in matches):
        raise HomeAssistantError(f"Input is not a general input: {identifier}")

    unique = []
    for match in matches:
        if not any(
            match[0] is existing[0] and match[1] == existing[1]
            for existing in unique
        ):
            unique.append(match)
    if len(unique) != 1:
        raise HomeAssistantError(f"Ambiguous input: {identifier}")
    return unique[0]


def _resolve_zone(hub: Any, identifier: str) -> str:
    """Resolve a zone ID or label to one immutable zone ID."""
    matches = []
    for immutable_id, info, key in _zone_records(hub):
        if identifier in {
            immutable_id,
            key,
            info.get("name"),
            info.get("label"),
        }:
            matches.append(immutable_id)

    unique = list(dict.fromkeys(matches))
    if not unique:
        raise HomeAssistantError(f"Unknown zone: {identifier}")
    if len(unique) != 1:
        raise HomeAssistantError(f"Ambiguous zone: {identifier}")
    return unique[0]


def _resolve_zone_list(hub: Any, identifiers: Any) -> list[str]:
    """Resolve and validate every requested zone before any write."""
    if not isinstance(identifiers, (list, tuple)):
        raise HomeAssistantError("zone_ids must be a list")

    resolved = []
    for identifier in identifiers:
        if not isinstance(identifier, str) or not identifier.strip():
            raise HomeAssistantError("Missing zone identifier")
        zone_id = _resolve_zone(hub, identifier)
        if zone_id in resolved:
            raise HomeAssistantError(f"Duplicate zone: {zone_id}")
        resolved.append(zone_id)
    return resolved


async def async_set_input_zones(
    call: ServiceCall, *, hass: HomeAssistant | None = None, hub: Any = None
) -> None:
    """Replace the route set for one named general input."""
    identifier = _required_text(call.data, _INPUT_ID)
    target_hub, input_id, _ = _resolve_input(hass, identifier, hub)
    zone_ids = _resolve_zone_list(target_hub, call.data.get(_ZONE_IDS))
    await target_hub.set_input_zones(input_id, zone_ids)


async def async_add_input_zone(
    call: ServiceCall, *, hass: HomeAssistant | None = None, hub: Any = None
) -> None:
    """Add one zone to one named general input without replacing other routes."""
    identifier = _required_text(call.data, _INPUT_ID)
    target_hub, input_id, _ = _resolve_input(hass, identifier, hub)
    zone_id = _resolve_zone(target_hub, _required_text(call.data, _ZONE_ID))
    await target_hub.add_input_zone(input_id, zone_id)


async def async_remove_input_zone(
    call: ServiceCall, *, hass: HomeAssistant | None = None, hub: Any = None
) -> None:
    """Remove one zone from one named general input without other changes."""
    identifier = _required_text(call.data, _INPUT_ID)
    target_hub, input_id, _ = _resolve_input(hass, identifier, hub)
    zone_id = _resolve_zone(target_hub, _required_text(call.data, _ZONE_ID))
    await target_hub.remove_input_zone(input_id, zone_id)


_HANDLERS = {
    SERVICE_SET_INPUT_ZONES: async_set_input_zones,
    SERVICE_ADD_INPUT_ZONE: async_add_input_zone,
    SERVICE_REMOVE_INPUT_ZONE: async_remove_input_zone,
}


async def async_setup_services(hass: HomeAssistant) -> None:
    """Register routing services once for the lifetime of configured entries."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get(_SERVICES_REGISTERED):
        return

    for service, handler in _HANDLERS.items():
        hass.services.async_register(
            DOMAIN,
            service,
            partial(handler, hass=hass),
            schema=_SERVICE_SCHEMAS[service],
        )
    domain_data[_SERVICES_REGISTERED] = True


async def async_unload_services(hass: HomeAssistant) -> None:
    """Remove routing services after the final config entry unloads."""
    domain_data = getattr(hass, "data", {}).get(DOMAIN, {})
    if not domain_data.pop(_SERVICES_REGISTERED, False):
        return

    for service in _HANDLERS:
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)
