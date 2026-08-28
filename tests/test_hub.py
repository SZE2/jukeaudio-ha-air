"""Tests for safe Juke hub write wrappers."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from custom_components.jukeaudio_ha_air.const import DOMAIN
from custom_components.jukeaudio_ha_air.hub import JukeAudioHub


class _FakeCoordinator:
    def __init__(self):
        self.refreshes = 0

    async def async_request_refresh(self):
        self.refreshes += 1


class _FakeClient:
    def __init__(self):
        self.calls = []

    async def _return(self, name, *args, value="ok"):
        self.calls.append((name, args))
        return value

    async def set_zone_mute(self, *args):
        return await self._return("set_zone_mute", *args, value="mute-ok")

    async def set_zone_enabled(self, *args):
        return await self._return("set_zone_enabled", *args)

    async def set_zone_inputs(self, *args):
        return await self._return("set_zone_inputs", *args)

    async def add_input_zone(self, *args):
        return await self._return("add_input_zone", *args)

    async def remove_input_zone(self, *args):
        return await self._return("remove_input_zone", *args)

    async def get_active_input(self, *args):
        return await self._return("get_active_input", *args, value={"input_id": "input-a"})

    async def set_active_input(self, *args):
        return await self._return("set_active_input", *args)

    async def get_streaming_inputs(self, *args):
        return await self._return(
            "get_streaming_inputs", *args, value={"input_ids": ["input-a"]}
        )

    async def set_zone_based_input_enabled(self, *args):
        return await self._return("set_zone_based_input_enabled", *args)


@pytest.fixture
def hub_and_fakes():
    hub = JukeAudioHub(None, "juke.local", "alice", "secret")
    hub.client = _FakeClient()
    hub.coordinator = _FakeCoordinator()
    return hub, hub.client, hub.coordinator


@pytest.mark.asyncio
async def test_set_zone_mute_delegates_and_refreshes_after_success(hub_and_fakes):
    """Mute wrapper delegates with credentials and refreshes cached state."""
    hub, client, coordinator = hub_and_fakes

    result = await hub.set_zone_mute("zone-1", True)

    assert result == "mute-ok"
    assert client.calls == [
        ("set_zone_mute", ("juke.local", "alice", "secret", "zone-1", True))
    ]
    assert coordinator.refreshes == 1


@pytest.mark.asyncio
async def test_set_zone_enabled_delegates_and_refreshes(hub_and_fakes):
    """Zone enable wrapper refreshes after its write succeeds."""
    hub, client, coordinator = hub_and_fakes

    await hub.set_zone_enabled("zone-1", False)

    assert client.calls == [
        ("set_zone_enabled", ("juke.local", "alice", "secret", "zone-1", False))
    ]
    assert coordinator.refreshes == 1


@pytest.mark.asyncio
async def test_set_zone_inputs_delegates_and_refreshes(hub_and_fakes):
    """Explicit zone input replacement is exposed through the client contract."""
    hub, client, coordinator = hub_and_fakes

    await hub.set_zone_inputs("zone-1", ["input-a", "input-b"])

    assert client.calls == [
        (
            "set_zone_inputs",
            ("juke.local", "alice", "secret", "zone-1", ["input-a", "input-b"]),
        )
    ]
    assert coordinator.refreshes == 1


@pytest.mark.asyncio
async def test_add_and_remove_input_zone_are_non_destructive_wrappers(hub_and_fakes):
    """Membership add/remove wrappers each refresh without replacing input lists."""
    hub, client, coordinator = hub_and_fakes

    await hub.add_input_zone("input-a", "zone-1")
    await hub.remove_input_zone("input-a", "zone-2")

    assert client.calls == [
        ("add_input_zone", ("juke.local", "alice", "secret", "input-a", "zone-1")),
        (
            "remove_input_zone",
            ("juke.local", "alice", "secret", "input-a", "zone-2"),
        ),
    ]
    assert coordinator.refreshes == 2


@pytest.mark.asyncio
async def test_active_input_wrappers_delegate_and_refresh_writes(hub_and_fakes):
    """Active-input reads delegate and only writes trigger a refresh."""
    hub, client, coordinator = hub_and_fakes

    active = await hub.get_active_input("zone-1")
    await hub.set_active_input("zone-1", "input-a")

    assert active == {"input_id": "input-a"}
    assert client.calls == [
        ("get_active_input", ("juke.local", "alice", "secret", "zone-1")),
        (
            "set_active_input",
            ("juke.local", "alice", "secret", "zone-1", "input-a"),
        ),
    ]
    assert coordinator.refreshes == 1


@pytest.mark.asyncio
async def test_streaming_inputs_read_does_not_refresh(hub_and_fakes):
    """Streaming-input reads use cached-state semantics and do not write."""
    hub, client, coordinator = hub_and_fakes

    result = await hub.get_streaming_inputs("zone-1")

    assert result == {"input_ids": ["input-a"]}
    assert client.calls == [
        ("get_streaming_inputs", ("juke.local", "alice", "secret", "zone-1"))
    ]
    assert coordinator.refreshes == 0


@pytest.mark.asyncio
async def test_set_zone_based_input_enabled_delegates_and_refreshes(hub_and_fakes):
    """Validated native input enablement refreshes after success."""
    hub, client, coordinator = hub_and_fakes

    await hub.set_zone_based_input_enabled("zone-1", "airplay2", True)

    assert client.calls == [
        (
            "set_zone_based_input_enabled",
            ("juke.local", "alice", "secret", "zone-1", "airplay2", True),
        )
    ]
    assert coordinator.refreshes == 1


@pytest.mark.asyncio
async def test_successful_write_does_not_cross_refresh_after_entry_unload():
    """A completed write is safe when its entry is already being removed."""
    other_coordinator = _FakeCoordinator()
    other_hub = JukeAudioHub(None, "other.local", "bob", "secret")
    hass = type(
        "FakeHass",
        (),
        {
            "data": {
                DOMAIN: {
                    "entry-2": {"hub": other_hub, "coordinator": other_coordinator},
                    "_routing_services_registered": True,
                }
            }
        },
    )()
    hub = JukeAudioHub(hass, "juke.local", "alice", "secret")
    hub._entry_id = "entry-1"
    hub.client = _FakeClient()
    hub.coordinator = None

    await hub.set_zone_mute("zone-1", True)

    assert hub.client.calls == [
        ("set_zone_mute", ("juke.local", "alice", "secret", "zone-1", True))
    ]
    assert other_coordinator.refreshes == 0


def test_get_coordinator_ignores_boolean_service_marker():
    """Service metadata is not treated as a config-entry mapping."""
    hass = type(
        "FakeHass",
        (),
        {"data": {DOMAIN: {"_routing_services_registered": True}}},
    )()
    hub = JukeAudioHub(hass, "juke.local", "alice", "secret")
    hub._entry_id = "entry-1"

    assert hub._get_coordinator() is None


@pytest.mark.asyncio
async def test_fetch_data_preserves_input_streaming_from_inputs_info():
    """The coordinator cache retains Juke's authoritative streaming indication."""
    hub = JukeAudioHub(None, "juke.local", "alice", "secret")
    hub._get_devices_info = AsyncMock(
        return_value=[
            {
                "device_id": "device-1",
                "config": {"name": "Juke"},
                "connection": {},
                "metrics": {},
                "attributes": {"serial_number": "serial-1", "firmware_version": "1.0"},
            }
        ]
    )
    hub._get_zones_info = AsyncMock(return_value=[])
    hub._get_input_info = AsyncMock(
        return_value=[
            {
                "input_id": "device-1-input-0",
                "input_class": 0,
                "input_type": "DLNA",
                "enabled": True,
                "streaming": True,
            }
        ]
    )

    await hub._fetch_data_v3()

    assert hub.jukes["device-1"].inputs["device-1-input-0"]["streaming"] is True
