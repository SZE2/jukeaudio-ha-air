"""Tests for automation-safe Juke input-to-zone routing services."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.jukeaudio_ha_air import async_unload_entry
from custom_components.jukeaudio_ha_air.const import DOMAIN
from custom_components.jukeaudio_ha_air.hub import JukeAudioHub
from custom_components.jukeaudio_ha_air.services import (
    SERVICE_ADD_INPUT_ZONE,
    SERVICE_REMOVE_INPUT_ZONE,
    SERVICE_SET_INPUT_ZONES,
    async_add_input_zone,
    async_remove_input_zone,
    async_set_input_zones,
    async_setup_services,
    async_unload_services,
)


class _FakeHub:
    def __init__(self) -> None:
        self.group_inputs = {
            "input-a": {
                "input_id": "input-a",
                "input_class": 0,
                "name": "Living Room Source",
                "zones": ["zone-1"],
            },
            "input-b": {
                "input_id": "input-b",
                "input_class": 0,
                "name": "Kitchen Source",
                "zones": ["zone-2"],
            },
            "native-airplay": {
                "input_id": "native-airplay",
                "input_class": 1,
                "name": "Living Room",
                "zones": ["zone-1"],
            },
        }
        self.jukes = {
            "amp-1": SimpleNamespace(
                zones={
                    "zone-1": {"zone_id": "zone-1", "name": "Living Room"},
                    "zone-2": {"zone_id": "zone-2", "name": "Kitchen"},
                },
                inputs=self.group_inputs,
            )
        }
        self.calls = []

    async def set_input_zones(self, input_id, zone_ids):
        self.calls.append((SERVICE_SET_INPUT_ZONES, input_id, zone_ids))

    async def add_input_zone(self, input_id, zone_id):
        self.calls.append((SERVICE_ADD_INPUT_ZONE, input_id, zone_id))

    async def remove_input_zone(self, input_id, zone_id):
        self.calls.append((SERVICE_REMOVE_INPUT_ZONE, input_id, zone_id))


class _FakeClient:
    def __init__(self) -> None:
        self.calls = []

    async def add_input_zone(self, *args):
        self.calls.append((SERVICE_ADD_INPUT_ZONE, args))
        return "added"

    async def remove_input_zone(self, *args):
        self.calls.append((SERVICE_REMOVE_INPUT_ZONE, args))
        return "removed"


class _FakeCoordinator:
    def __init__(self) -> None:
        self.refreshes = 0

    async def async_request_refresh(self):
        self.refreshes += 1


class _FailingClient:
    async def remove_input_zone(self, *args):
        raise RuntimeError("write failed")

    async def add_input_zone(self, *args):
        raise AssertionError("add must not run after a failed removal")


class _PartiallyFailingClient:
    """Model route mutations and fail on selected transport attempts."""

    def __init__(self, fail_on):
        self.routes = {"input-a": ["zone-1", "zone-2"], "input-b": ["zone-3"]}
        self.calls = []
        self.fail_on = set(fail_on)
        self.attempt = 0

    def _record(self, operation, args):
        self.attempt += 1
        input_id, zone_id = args[-2:]
        self.calls.append((operation, input_id, zone_id))
        if self.attempt in self.fail_on:
            raise RuntimeError("transport failed")

    async def remove_input_zone(self, *args):
        self._record(SERVICE_REMOVE_INPUT_ZONE, args)
        self.routes[args[-2]].remove(args[-1])
        return "removed"

    async def add_input_zone(self, *args):
        self._record(SERVICE_ADD_INPUT_ZONE, args)
        if args[-1] not in self.routes[args[-2]]:
            self.routes[args[-2]].append(args[-1])
        return "added"


class _FakeServices:
    def __init__(self) -> None:
        self.registered = {}
        self.register_calls = []
        self.removed = []

    def has_service(self, domain, service):
        return (domain, service) in self.registered

    def async_register(self, domain, service, handler, schema=None):
        self.register_calls.append((domain, service, handler, schema))
        self.registered[(domain, service)] = handler

    def async_remove(self, domain, service):
        self.removed.append((domain, service))
        self.registered.pop((domain, service), None)


class _FakeConfigEntries:
    async def async_unload_platforms(self, entry, platforms):
        return True


@pytest.fixture
def hass_and_hub():
    hub = _FakeHub()
    hass = SimpleNamespace(
        data={DOMAIN: {"entry-1": {"hub": hub, "coordinator": object()}}},
        services=_FakeServices(),
        config_entries=_FakeConfigEntries(),
    )
    return hass, hub


def _call(data):
    return SimpleNamespace(data=data)


@pytest.mark.asyncio
async def test_set_input_zones_replaces_only_the_named_input(hass_and_hub):
    """Set replaces one general input route and never delegates other inputs."""
    _, hub = hass_and_hub

    await async_set_input_zones(
        _call({"input_id": "input-a", "zone_ids": ["zone-2"]}),
        hub=hub,
    )

    assert hub.calls == [(SERVICE_SET_INPUT_ZONES, "input-a", ["zone-2"])]


@pytest.mark.asyncio
async def test_add_input_zone_resolves_names_and_is_additive(hass_and_hub):
    """Add resolves friendly labels once and delegates an additive operation."""
    _, hub = hass_and_hub

    await async_add_input_zone(
        _call({"input_id": "Living Room Source", "zone_id": "Kitchen"}),
        hub=hub,
    )

    assert hub.calls == [(SERVICE_ADD_INPUT_ZONE, "input-a", "zone-2")]


@pytest.mark.asyncio
async def test_remove_input_zone_is_non_destructive(hass_and_hub):
    """Remove delegates only the requested input/zone membership."""
    _, hub = hass_and_hub

    await async_remove_input_zone(
        _call({"input_id": "input-a", "zone_id": "zone-1"}),
        hub=hub,
    )

    assert hub.calls == [(SERVICE_REMOVE_INPUT_ZONE, "input-a", "zone-1")]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "data, message",
    [
        ({"input_id": "missing", "zone_id": "zone-1"}, "Unknown input"),
        ({"input_id": "native-airplay", "zone_id": "zone-1"}, "general input"),
        ({"input_id": "input-a", "zone_id": "missing"}, "Unknown zone"),
    ],
)
async def test_invalid_add_input_zone_has_no_hub_write(hass_and_hub, data, message):
    """Invalid input or zone identifiers fail closed before any write."""
    _, hub = hass_and_hub

    with pytest.raises(HomeAssistantError, match=message):
        await async_add_input_zone(_call(data), hub=hub)

    assert hub.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "data, message",
    [
        ({"zone_ids": ["zone-1"]}, "Missing input_id"),
        (
            {"input_id": "native-airplay", "zone_ids": ["zone-1"]},
            "general input",
        ),
    ],
)
async def test_invalid_set_input_zones_has_no_hub_write(hass_and_hub, data, message):
    """Set rejects a missing or non-general input before any route write."""
    _, hub = hass_and_hub

    with pytest.raises(HomeAssistantError, match=message):
        await async_set_input_zones(_call(data), hub=hub)

    assert hub.calls == []


@pytest.mark.asyncio
async def test_set_rejects_duplicate_resolved_zone_ids_before_write(hass_and_hub):
    """Duplicate IDs are rejected even when supplied as ID and friendly name."""
    _, hub = hass_and_hub

    with pytest.raises(HomeAssistantError, match="Duplicate zone"):
        await async_set_input_zones(
            _call({"input_id": "input-a", "zone_ids": ["zone-1", "Living Room"]}),
            hub=hub,
        )

    assert hub.calls == []


@pytest.mark.asyncio
async def test_set_rejects_unknown_zone_before_write(hass_and_hub):
    """A single unknown zone prevents the replacement from being sent."""
    _, hub = hass_and_hub

    with pytest.raises(HomeAssistantError, match="Unknown zone"):
        await async_set_input_zones(
            _call({"input_id": "input-a", "zone_ids": ["zone-1", "missing"]}),
            hub=hub,
        )

    assert hub.calls == []


@pytest.mark.asyncio
async def test_invalid_zone_validation_does_not_write_external_client():
    """Invalid route input is rejected before a client mutation is attempted."""
    hub = JukeAudioHub(None, "juke.local", "alice", "secret")
    hub.group_inputs = {
        "input-a": {
            "input_id": "input-a",
            "input_class": 0,
            "zones": ["zone-1"],
        }
    }
    hub.jukes = {
        "amp-1": SimpleNamespace(
            zones={"zone-1": {"zone_id": "zone-1", "name": "Living Room"}}
        )
    }
    client = _PartiallyFailingClient({1})
    hub.client = client

    with pytest.raises(HomeAssistantError, match="Unknown zone"):
        await async_set_input_zones(
            _call({"input_id": "input-a", "zone_ids": ["missing"]}),
            hub=hub,
        )

    assert client.calls == []


@pytest.mark.asyncio
async def test_service_registration_is_idempotent_and_unload_removes_handlers(
    hass_and_hub,
):
    """Reloads do not duplicate handlers and final unload removes every service."""
    hass, _ = hass_and_hub

    await async_setup_services(hass)
    await async_setup_services(hass)

    assert set(hass.services.registered) == {
        (DOMAIN, SERVICE_SET_INPUT_ZONES),
        (DOMAIN, SERVICE_ADD_INPUT_ZONE),
        (DOMAIN, SERVICE_REMOVE_INPUT_ZONE),
    }
    assert len(hass.services.register_calls) == 3

    await hass.services.registered[(DOMAIN, SERVICE_ADD_INPUT_ZONE)](
        _call({"input_id": "input-a", "zone_id": "zone-1"})
    )
    assert hass.data[DOMAIN]["entry-1"]["hub"].calls == [
        (SERVICE_ADD_INPUT_ZONE, "input-a", "zone-1")
    ]

    await async_unload_services(hass)

    assert hass.services.registered == {}
    assert set(hass.services.removed) == {
        (DOMAIN, SERVICE_SET_INPUT_ZONES),
        (DOMAIN, SERVICE_ADD_INPUT_ZONE),
        (DOMAIN, SERVICE_REMOVE_INPUT_ZONE),
    }


@pytest.mark.asyncio
async def test_entry_unload_removes_services_only_after_last_hub(hass_and_hub):
    """A surviving config entry keeps handlers available; final unload removes them."""
    hass, _ = hass_and_hub
    await async_setup_services(hass)
    hass.data[DOMAIN]["entry-2"] = {"hub": _FakeHub(), "coordinator": object()}

    assert await async_unload_entry(hass, SimpleNamespace(entry_id="entry-1")) is True
    assert hass.services.registered

    assert await async_unload_entry(hass, SimpleNamespace(entry_id="entry-2")) is True
    assert hass.services.registered == {}


@pytest.mark.asyncio
async def test_entry_unload_invalidates_hub_coordinator_before_data_removal():
    """Unloading removes the hub's direct refresh reference before its entry."""
    coordinator = _FakeCoordinator()
    hub = JukeAudioHub(None, "juke.local", "alice", "secret")
    hub._entry_id = "entry-1"
    hub.coordinator = coordinator
    hass = SimpleNamespace(
        data={DOMAIN: {"entry-1": {"hub": hub, "coordinator": coordinator}}},
        services=_FakeServices(),
        config_entries=_FakeConfigEntries(),
    )

    assert await async_unload_entry(hass, SimpleNamespace(entry_id="entry-1")) is True

    assert hub.coordinator is None
    assert "entry-1" not in hass.data[DOMAIN]


@pytest.mark.asyncio
async def test_hub_set_input_zones_changes_only_named_input_and_refreshes():
    """Hub replacement is composed from scoped membership writes."""
    hub = JukeAudioHub(None, "juke.local", "alice", "secret")
    hub.group_inputs = {
        "input-a": {"input_id": "input-a", "input_class": 0, "zones": ["zone-1"]},
        "input-b": {"input_id": "input-b", "input_class": 0, "zones": ["zone-2"]},
    }
    hub.client = _FakeClient()
    hub.coordinator = _FakeCoordinator()

    await hub.set_input_zones("input-a", ["zone-2"])

    assert hub.client.calls == [
        (
            SERVICE_REMOVE_INPUT_ZONE,
            ("juke.local", "alice", "secret", "input-a", "zone-1"),
        ),
        (
            SERVICE_ADD_INPUT_ZONE,
            ("juke.local", "alice", "secret", "input-a", "zone-2"),
        ),
    ]
    assert hub.coordinator.refreshes == 1


@pytest.mark.asyncio
async def test_hub_set_input_zones_does_not_refresh_when_a_write_fails():
    """A failed membership write cannot trigger a coordinator refresh."""
    hub = JukeAudioHub(None, "juke.local", "alice", "secret")
    hub.group_inputs = {
        "input-a": {"input_id": "input-a", "input_class": 0, "zones": ["zone-1"]},
    }
    hub.client = _FailingClient()
    hub.coordinator = _FakeCoordinator()

    with pytest.raises(HomeAssistantError, match="rollback succeeded"):
        await hub.set_input_zones("input-a", ["zone-2"])

    assert hub.coordinator.refreshes == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("fail_on", "rollback_message"),
    [({2}, "rollback succeeded"), ({2, 3}, "rollback failed")],
)
async def test_hub_set_input_zones_rolls_back_only_named_input_after_failure(
    fail_on, rollback_message
):
    """A partial route write attempts to restore the exact cached mapping."""
    hub = JukeAudioHub(None, "juke.local", "alice", "secret")
    hub.group_inputs = {
        "input-a": {
            "input_id": "input-a",
            "input_class": 0,
            "zones": ["zone-1", "zone-2"],
        },
        "input-b": {
            "input_id": "input-b",
            "input_class": 0,
            "zones": ["zone-3"],
        },
    }
    client = _PartiallyFailingClient(fail_on)
    hub.client = client
    hub.coordinator = _FakeCoordinator()

    with pytest.raises(HomeAssistantError, match=rollback_message):
        await hub.set_input_zones("input-a", ["zone-3"])

    assert client.calls == [
        (SERVICE_REMOVE_INPUT_ZONE, "input-a", "zone-1"),
        (SERVICE_REMOVE_INPUT_ZONE, "input-a", "zone-2"),
        (SERVICE_ADD_INPUT_ZONE, "input-a", "zone-1"),
    ]
    expected_route = ["zone-2", "zone-1"] if fail_on == {2} else ["zone-2"]
    assert client.routes["input-a"] == expected_route
    assert client.routes["input-b"] == ["zone-3"]
    assert hub.coordinator.refreshes == 0
