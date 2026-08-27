"""Tests for Juke general-input-to-zone routing switches."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from homeassistant.components.switch import SwitchEntity

from custom_components.jukeaudio_ha_air.const import DOMAIN
from custom_components.jukeaudio_ha_air.switch import async_setup_entry


class _FakeHub:
    def __init__(self) -> None:
        self.group_inputs = {
            f"input-{index}": {
                "input_id": f"input-{index}",
                "input_class": 0,
                "name": f"Input {index}",
                "zones": [],
            }
            for index in range(4)
        }
        self.jukes = {
            "amp-1": SimpleNamespace(
                zones={
                    f"zone-{index}": {
                        "zone_id": f"zone-{index}",
                        "name": f"Zone {index}",
                        "input": ["native-airplay", "native-spotify"],
                    }
                    for index in range(6)
                },
                inputs={
                    **self.group_inputs,
                    "native-airplay": {
                        "input_id": "native-airplay",
                        "input_class": 1,
                        "name": "AirPlay",
                        "input_type": "Airplay2",
                    },
                    "native-spotify": {
                        "input_id": "native-spotify",
                        "input_class": 1,
                        "name": "Spotify",
                        "input_type": "Spotify",
                    },
                },
            )
        }


def _make_hass(hub: _FakeHub):
    return SimpleNamespace(
        data={
            DOMAIN: {
                "entry-1": {
                    "hub": hub,
                    "coordinator": SimpleNamespace(),
                }
            }
        }
    )


@pytest.mark.asyncio
async def test_setup_creates_one_switch_for_each_general_input_and_zone_pair():
    """Four general inputs and six zones create the complete 24-state matrix."""
    entities = []
    hub = _FakeHub()
    entry = SimpleNamespace(entry_id="entry-1")

    await async_setup_entry(_make_hass(hub), entry, entities.extend)

    assert len(entities) == 24
    assert all(isinstance(entity, SwitchEntity) for entity in entities)


@pytest.mark.asyncio
async def test_switch_identity_and_name_are_pair_based_and_reordering_stable():
    """Input/zone ordering does not affect pair identity or display names."""
    hub = _FakeHub()
    entry = SimpleNamespace(entry_id="entry-1")
    first = []
    await async_setup_entry(_make_hass(hub), entry, first.extend)

    first_by_id = {entity.unique_id: entity.name for entity in first}
    assert first_by_id["route_input-2_zone-4"] == "Input 2 to Zone 4"

    hub.group_inputs = dict(reversed(list(hub.group_inputs.items())))
    juke = hub.jukes["amp-1"]
    juke.zones = dict(reversed(list(juke.zones.items())))
    second = []
    await async_setup_entry(_make_hass(hub), entry, second.extend)

    assert {entity.unique_id: entity.name for entity in second} == first_by_id


@pytest.mark.asyncio
async def test_switches_exclude_non_general_and_native_zone_inputs():
    """Only class-zero inputs participate in the routing matrix."""
    hub = _FakeHub()
    hub.group_inputs["native-airplay"] = {
        "input_id": "native-airplay",
        "input_class": 1,
        "name": "AirPlay",
        "zones": ["zone-0"],
    }
    hub.group_inputs["native-spotify"] = {
        "input_id": "native-spotify",
        "input_class": 1,
        "name": "Spotify",
        "zones": ["zone-0"],
    }
    entry = SimpleNamespace(entry_id="entry-1")
    entities = []

    await async_setup_entry(_make_hass(hub), entry, entities.extend)

    assert len(entities) == 24
    assert all("native-airplay" not in entity.unique_id for entity in entities)
    assert all("native-spotify" not in entity.unique_id for entity in entities)


@pytest.mark.asyncio
async def test_is_on_uses_cached_input_zones_not_active_playback():
    """Routing state is independent of the zone's active playback input."""
    hub = _FakeHub()
    hub.group_inputs["input-0"]["zones"] = ["zone-0"]
    hub.jukes["amp-1"].zones["zone-0"]["active_input"] = "input-3"
    entry = SimpleNamespace(entry_id="entry-1")
    entities = []

    await async_setup_entry(_make_hass(hub), entry, entities.extend)
    route = next(entity for entity in entities if entity.unique_id == "route_input-0_zone-0")

    assert route.is_on is True

    hub.jukes["amp-1"].zones["zone-0"]["active_input"] = None
    hub.group_inputs["input-0"]["zones"] = []
    assert route.is_on is False


class _RoutingHub(_FakeHub):
    def __init__(self) -> None:
        super().__init__()
        self.calls = []

    async def add_input_zone(self, input_id, zone_id):
        self.calls.append(("add_input_zone", input_id, zone_id))

    async def remove_input_zone(self, input_id, zone_id):
        self.calls.append(("remove_input_zone", input_id, zone_id))


@pytest.mark.asyncio
async def test_turning_a_switch_calls_only_non_destructive_membership_operation():
    """Toggle operations add/remove one pair without replacing or changing playback."""
    hub = _RoutingHub()
    entry = SimpleNamespace(entry_id="entry-1")
    entities = []
    await async_setup_entry(_make_hass(hub), entry, entities.extend)
    route = next(entity for entity in entities if entity.unique_id == "route_input-0_zone-0")

    await route.async_turn_on()
    await route.async_turn_off()

    assert hub.calls == [
        ("add_input_zone", "input-0", "zone-0"),
        ("remove_input_zone", "input-0", "zone-0"),
    ]


@pytest.mark.asyncio
async def test_toggling_one_pair_does_not_change_other_cached_mapping_states():
    """Independent matrix cells retain their cached mapping state."""
    hub = _RoutingHub()
    hub.group_inputs["input-0"]["zones"] = ["zone-0", "zone-1"]
    hub.group_inputs["input-1"]["zones"] = ["zone-0"]
    entry = SimpleNamespace(entry_id="entry-1")
    entities = []
    await async_setup_entry(_make_hass(hub), entry, entities.extend)
    route_a = next(entity for entity in entities if entity.unique_id == "route_input-0_zone-0")
    route_b = next(entity for entity in entities if entity.unique_id == "route_input-0_zone-1")
    route_c = next(entity for entity in entities if entity.unique_id == "route_input-1_zone-0")

    before = (route_a.is_on, route_b.is_on, route_c.is_on)
    await route_a.async_turn_off()

    assert (route_a.is_on, route_b.is_on, route_c.is_on) == before


def test_switch_platform_is_registered_without_removing_existing_platforms():
    """The switch platform is forwarded alongside the existing platforms."""
    from homeassistant.const import Platform

    from custom_components.jukeaudio_ha_air import PLATFORMS

    assert PLATFORMS == [Platform.SENSOR, Platform.MEDIA_PLAYER, Platform.SWITCH]
