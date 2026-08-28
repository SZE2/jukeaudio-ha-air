"""Tests for the Juke zone media-player entities."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.components.media_player import MediaPlayerEntityFeature, MediaPlayerState
from homeassistant.exceptions import HomeAssistantError

from custom_components.jukeaudio_ha_air.airplay import dump_airplay_targets, load_airplay_targets
from custom_components.jukeaudio_ha_air.const import CONF_AIRPLAY_TARGETS, DOMAIN
from custom_components.jukeaudio_ha_air.media_player import Zone, async_setup_entry


ZONE_ID = "zone-1"


class _FakeZoneHub:
    def __init__(self, coordinator=None):
        self.calls = []
        self.coordinator = coordinator

    async def set_zone_mute(self, zone_id, muted):
        self.calls.append(("set_zone_mute", zone_id, muted))

    async def set_zone_volume(self, zone_id, volume):
        self.calls.append(("set_zone_volume", zone_id, volume))

    async def set_active_input(self, zone_id, input_id):
        self.calls.append(("set_active_input", zone_id, input_id))

    async def set_zone_enabled(self, zone_id, enabled):
        self.calls.append(("set_zone_enabled", zone_id, enabled))


class _RefreshCoordinator:
    def __init__(self):
        self.refreshes = 0

    async def async_request_refresh(self):
        self.refreshes += 1


class _RefreshingZoneHub(_FakeZoneHub):
    async def set_active_input(self, zone_id, input_id):
        await super().set_active_input(zone_id, input_id)
        await self.coordinator.async_request_refresh()


def _make_zone(
    zone_data, hub=None, *, zone_id=ZONE_ID, config_entry=None, coordinator=None, inputs=None
):
    """Build a zone entity around the coordinator cache shape."""
    juke = SimpleNamespace(
        zones={zone_id: zone_data},
        inputs=inputs or {},
        hub=hub or SimpleNamespace(),
    )
    return Zone(juke, coordinator or SimpleNamespace(), config_entry, zone_id)


def test_idle_active_input_has_no_playing_media_title():
    """An active but idle input must not be described as playing media."""
    zone = _make_zone(
        {
            "name": "Living Room",
            "volume": 42,
            "muted": False,
            "enabled": True,
            "active_input": "input-1",
        },
        inputs={
            "input-1": {
                "input_id": "input-1",
                "input_class": 0,
                "name": "Juke Bluetooth",
                "streaming": False,
            }
        },
    )

    assert zone.state is MediaPlayerState.ON
    assert zone.media_title is None


def _airplay_record(*, zone_id, device_id, player_uuid, protocol_mode):
    return {
        "zone_id": zone_id,
        "host": f"{zone_id}.receiver.example",
        "port": 7000 if zone_id == "zone-1" else 7001,
        "device_id": device_id,
        "player_uuid": player_uuid,
        "service_name": f"{zone_id} receiver",
        "txt": {"deviceid": device_id},
        "protocol_mode": protocol_mode,
    }


@pytest.mark.asyncio
async def test_media_player_platform_creates_only_physical_zones():
    """General inputs are configuration/routing controls, never HA media players."""
    juke = SimpleNamespace(
        zones={
            "zone-1": {
                "name": "Living Room",
                "volume": 42,
                "muted": False,
                "enabled": True,
                "active_input": None,
            }
        },
        inputs={
            "input-1": {
                "input_id": "input-1",
                "input_class": 0,
                "name": "Juke Bluetooth",
                "input_type": "Airplay2",
            }
        },
    )
    hub = SimpleNamespace(jukes={"amp-1": juke})
    hass = SimpleNamespace(
        data={DOMAIN: {"entry-1": {"hub": hub, "coordinator": SimpleNamespace()}}}
    )
    entities = []

    await async_setup_entry(hass, SimpleNamespace(entry_id="entry-1"), entities.extend)

    assert len(entities) == 1
    assert isinstance(entities[0], Zone)


@pytest.mark.parametrize("muted", [True, False])
def test_zone_is_volume_muted_follows_cached_zone_info(muted):
    """The mute state comes from the cached zone information."""
    zone = _make_zone(
        {
            "name": "Living Room",
            "volume": 42,
            "muted": muted,
            "enabled": True,
            "active_input": None,
        }
    )

    assert zone.is_volume_muted is muted


@pytest.mark.parametrize("muted", [True, False])
@pytest.mark.asyncio
async def test_async_mute_volume_delegates_without_changing_volume(muted):
    """Mute requests use the native zone mute operation only."""
    hub = _FakeZoneHub()
    zone = _make_zone(
        {
            "name": "Living Room",
            "volume": 42,
            "muted": not muted,
            "enabled": True,
            "active_input": None,
        },
        hub,
    )
    zone.async_update = AsyncMock()
    zone.hass = SimpleNamespace(async_add_executor_job=AsyncMock())
    zone.mute_volume = Mock()

    await zone.async_mute_volume(muted)

    assert hub.calls == [("set_zone_mute", ZONE_ID, muted)]
    zone.mute_volume.assert_not_called()


def test_zone_supported_features_include_volume_mute():
    """Zones advertise native volume mute alongside existing controls."""
    zone = _make_zone(
        {
            "name": "Living Room",
            "volume": 42,
            "muted": False,
            "enabled": True,
            "active_input": None,
        }
    )

    assert zone.supported_features & MediaPlayerEntityFeature.VOLUME_MUTE


def test_zone_without_an_active_input_has_no_source_value():
    """An inactive zone does not invent a literal source named ``None``."""
    zone = _make_zone(
        {
            "name": "Living Room",
            "volume": 42,
            "muted": False,
            "enabled": True,
            "active_input": None,
        }
    )

    assert zone.source is None


def test_zone_exposes_its_immutable_id_for_dashboard_route_controls():
    """The bundled panel can match route controls to their physical zone."""
    zone = _make_zone(
        {
            "name": "Living Room",
            "volume": 42,
            "muted": False,
            "enabled": True,
            "active_input": None,
        }
    )

    assert zone.extra_state_attributes["juke_zone_id"] == ZONE_ID


@pytest.mark.asyncio
async def test_zone_power_controls_delegate_to_the_juke_enable_operation():
    """Zone power is an enabled-state control, not inferred from playback."""
    hub = _FakeZoneHub()
    zone = _make_zone(
        {
            "name": "Living Room",
            "volume": 42,
            "muted": False,
            "enabled": True,
            "active_input": None,
        },
        hub,
    )

    assert zone.supported_features & MediaPlayerEntityFeature.TURN_ON
    assert zone.supported_features & MediaPlayerEntityFeature.TURN_OFF

    await zone.async_turn_off()
    await zone.async_turn_on()

    assert hub.calls == [
        ("set_zone_enabled", ZONE_ID, False),
        ("set_zone_enabled", ZONE_ID, True),
    ]


def test_zone_advertises_play_media_only_for_exact_raop_mapping():
    """Zones advertise direct playback only for an exact RAOP fallback target."""
    config_entry = SimpleNamespace(
        options={
            CONF_AIRPLAY_TARGETS: dump_airplay_targets(
                load_airplay_targets(
                    {
                        "zone-1": _airplay_record(
                            zone_id="zone-1",
                            device_id="AA:BB:CC:DD:EE:01",
                            player_uuid="player-1",
                            protocol_mode="raop_fallback",
                        ),
                        "zone-2": _airplay_record(
                            zone_id="zone-2",
                            device_id="AA:BB:CC:DD:EE:02",
                            player_uuid="player-2",
                            protocol_mode="airplay2",
                        ),
                    }
                )
            ),
        }
    )
    zone_1 = _make_zone(
        {"name": "Living Room", "volume": 42, "muted": False, "enabled": True, "active_input": None},
        zone_id="zone-1",
        config_entry=config_entry,
    )
    zone_2 = _make_zone(
        {"name": "Kitchen", "volume": 42, "muted": False, "enabled": True, "active_input": None},
        zone_id="zone-2",
        config_entry=config_entry,
    )

    assert zone_1.supported_features & MediaPlayerEntityFeature.PLAY_MEDIA
    assert not zone_2.supported_features & MediaPlayerEntityFeature.PLAY_MEDIA


@pytest.mark.parametrize(
    "options",
    [
        {},
        {CONF_AIRPLAY_TARGETS: []},
        {CONF_AIRPLAY_TARGETS: {"zone-1": {"zone_id": "wrong"}}},
    ],
)
def test_zone_hides_play_media_when_raop_options_are_not_valid(options):
    """Incomplete or malformed options keep a zone control-only."""
    zone = _make_zone(
        {"name": "Living Room", "volume": 42, "muted": False, "enabled": True, "active_input": None},
        zone_id=ZONE_ID,
        config_entry=SimpleNamespace(options=options),
    )

    assert not zone.supported_features & MediaPlayerEntityFeature.PLAY_MEDIA


@pytest.mark.asyncio
async def test_zone_play_media_uses_integrated_raop_without_mutating_juke(monkeypatch):
    """Direct playback forwards the exact URL and leaves Juke state untouched."""
    sender_call = AsyncMock()
    monkeypatch.setattr(
        "custom_components.jukeaudio_ha_air.media_player.DirectRaopClient.async_play_media",
        sender_call,
    )
    config_entry = SimpleNamespace(
        options={
            CONF_AIRPLAY_TARGETS: dump_airplay_targets(
                load_airplay_targets(
                    {
                        "zone-1": _airplay_record(
                            zone_id="zone-1",
                            device_id="AA:BB:CC:DD:EE:01",
                            player_uuid="player-1",
                            protocol_mode="raop_fallback",
                        )
                    }
                )
            ),
        }
    )
    hub = _FakeZoneHub()
    zone = _make_zone(
        {"name": "Living Room", "volume": 42, "muted": False, "enabled": True, "active_input": None},
        hub,
        config_entry=config_entry,
    )
    before = dict(zone._juke.zones[ZONE_ID])

    await zone.async_play_media("audio/mpeg", "https://media.example/exact.mp3")

    sender_call.assert_awaited_once_with(ZONE_ID, "https://media.example/exact.mp3")
    assert hub.calls == []
    assert zone._juke.zones[ZONE_ID] == before


def test_zone_state_prioritizes_disabled_over_playing_and_ignores_mute():
    """Disabled zones stay off, while mute does not change playback state."""
    disabled_zone = _make_zone(
        {
            "name": "Living Room",
            "volume": 42,
            "muted": False,
            "enabled": False,
            "active_input": "input-1",
        }
    )
    muted_zone = _make_zone(
        {
            "name": "Living Room",
            "volume": 42,
            "muted": True,
            "enabled": True,
            "active_input": "input-1",
        }
    )
    muted_zone._juke.inputs = {
        "input-1": {
            "input_id": "input-1",
            "input_class": 1,
            "input_type": "Spotify",
            "enabled": True,
            "streaming": True,
        }
    }

    assert disabled_zone.state is MediaPlayerState.OFF
    assert muted_zone.state is MediaPlayerState.PLAYING


def test_zone_with_an_active_but_non_streaming_input_is_on_not_playing():
    """Juke source selection alone is not proof of active media playback."""
    zone = _make_zone(
        {
            "name": "Living Room",
            "volume": 42,
            "muted": False,
            "enabled": True,
            "input": ["input-airplay"],
            "active_input": "input-airplay",
        }
    )
    zone._juke.inputs = {
        "input-airplay": {
            "input_id": "input-airplay",
            "input_class": 2,
            "input_type": "Airplay2",
            "enabled": True,
            "streaming": False,
        }
    }

    assert zone.state is MediaPlayerState.ON


def test_zone_source_uses_juke_active_input_and_lists_only_streaming_choices():
    """Zone selection follows Juke's active and streaming input model."""
    hub = _FakeZoneHub()
    inputs = {
        "input-dlna": {
            "input_id": "input-dlna",
            "name": "Juke-DLNA2",
            "input_class": 0,
            "input_type": "DLNA",
            "enabled": True,
            "streaming": True,
        },
        "input-airplay": {
            "input_id": "input-airplay",
            "name": "zone-1",
            "input_class": 2,
            "input_type": "Airplay2",
            "enabled": True,
            "streaming": False,
        },
        "input-spotify": {
            "input_id": "input-spotify",
            "name": "zone-1",
            "input_class": 1,
            "input_type": "Spotify",
            "enabled": True,
            "streaming": False,
        },
    }
    zone = _make_zone(
        {
            "name": "Living Room",
            "volume": 42,
            "muted": False,
            "enabled": True,
            "input": ["input-dlna", "input-airplay", "input-spotify"],
            "active_input": "input-dlna",
        },
        hub,
    )
    zone._juke.inputs = inputs

    assert zone.source == "Juke-DLNA2"
    assert zone.source_list == ["Juke-DLNA2"]
    assert zone.extra_state_attributes["juke_input_options"] == [
        {
            "input_id": "input-dlna",
            "source": "Juke-DLNA2",
            "input_type": "DLNA",
            "enabled": True,
            "streaming": True,
            "selectable": True,
        },
        {
            "input_id": "input-airplay",
            "source": "AirPlay 2",
            "input_type": "Airplay2",
            "enabled": True,
            "streaming": False,
            "selectable": False,
        },
        {
            "input_id": "input-spotify",
            "source": "Spotify",
            "input_type": "Spotify",
            "enabled": True,
            "streaming": False,
            "selectable": False,
        },
    ]


def test_zone_uses_cached_shared_input_when_not_owned_by_its_device():
    """A zone can select a general input cached at the hub level."""
    hub = _FakeZoneHub()
    hub.group_inputs = {
        "input-dlna": {
            "input_id": "input-dlna",
            "name": "Juke-DLNA2",
            "input_class": 0,
            "input_type": "DLNA",
            "enabled": True,
            "streaming": True,
        }
    }
    zone = _make_zone(
        {
            "name": "Living Room",
            "volume": 42,
            "muted": False,
            "enabled": True,
            "input": ["input-dlna"],
            "active_input": "input-dlna",
        },
        hub,
    )

    assert zone.source == "Juke-DLNA2"
    assert zone.source_list == ["Juke-DLNA2"]
    assert zone.extra_state_attributes["juke_input_options"][0]["input_id"] == "input-dlna"


def test_zone_does_not_offer_disabled_streaming_input():
    """A mapped input stays unavailable when Juke has disabled it."""
    zone = _make_zone(
        {
            "name": "Living Room",
            "volume": 42,
            "muted": False,
            "enabled": True,
            "input": ["input-dlna"],
            "active_input": None,
        }
    )
    zone._juke.inputs = {
        "input-dlna": {
            "input_id": "input-dlna",
            "name": "Juke-DLNA2",
            "input_class": 0,
            "input_type": "DLNA",
            "enabled": False,
            "streaming": True,
        }
    }

    assert zone.source_list == []
    assert zone.extra_state_attributes["juke_input_options"][0] == {
        "input_id": "input-dlna",
        "source": "Juke-DLNA2",
        "input_type": "DLNA",
        "enabled": False,
        "streaming": True,
        "selectable": False,
    }


@pytest.mark.asyncio
async def test_zone_source_selection_sets_active_input_not_input_assignment():
    """Selecting a listed source changes only Juke's active input."""
    hub = _FakeZoneHub()
    zone = _make_zone(
        {
            "name": "Living Room",
            "volume": 42,
            "muted": False,
            "enabled": True,
            "input": ["input-dlna"],
            "active_input": "input-dlna",
        },
        hub,
    )
    zone._juke.inputs = {
        "input-dlna": {
            "input_id": "input-dlna",
            "name": "Juke-DLNA2",
            "input_class": 0,
            "input_type": "DLNA",
            "enabled": True,
            "streaming": True,
        }
    }
    zone.async_update = AsyncMock()

    await zone.async_select_source("Juke-DLNA2")

    assert hub.calls == [("set_active_input", ZONE_ID, "input-dlna")]


@pytest.mark.asyncio
async def test_zone_source_selection_relies_on_hub_for_the_single_refresh():
    """Active-input writes must not request a second coordinator refresh."""
    coordinator = _RefreshCoordinator()
    hub = _RefreshingZoneHub(coordinator)
    zone = _make_zone(
        {
            "name": "Living Room",
            "volume": 42,
            "muted": False,
            "enabled": True,
            "input": ["input-dlna"],
            "active_input": "input-dlna",
        },
        hub,
        coordinator=coordinator,
    )
    zone._juke.inputs = {
        "input-dlna": {
            "input_id": "input-dlna",
            "name": "Juke-DLNA2",
            "input_class": 0,
            "input_type": "DLNA",
            "enabled": True,
            "streaming": True,
        }
    }

    await zone.async_select_source("Juke-DLNA2")

    assert coordinator.refreshes == 1


@pytest.mark.asyncio
async def test_zone_rejects_inactive_source_selection():
    """The integration does not request a source Juke marks unavailable."""
    hub = _FakeZoneHub()
    zone = _make_zone(
        {
            "name": "Living Room",
            "volume": 42,
            "muted": False,
            "enabled": True,
            "input": ["input-airplay"],
            "active_input": None,
        },
        hub,
    )
    zone._juke.inputs = {
        "input-airplay": {
            "input_id": "input-airplay",
            "name": "zone-1",
            "input_class": 2,
            "input_type": "Airplay2",
            "enabled": True,
            "streaming": False,
        }
    }

    with pytest.raises(HomeAssistantError, match="not currently selectable"):
        await zone.async_select_source("AirPlay 2")

    assert hub.calls == []


@pytest.mark.asyncio
async def test_zone_explains_when_a_known_general_input_is_not_routed():
    """Automation failures identify a missing route instead of a vague unknown source."""
    hub = _FakeZoneHub()
    hub.group_inputs = {
        "input-dlna": {
            "input_id": "input-dlna",
            "name": "Juke-DLNA2",
            "input_class": 0,
            "input_type": "DLNA",
            "enabled": True,
            "streaming": True,
        }
    }
    zone = _make_zone(
        {
            "name": "Greatroom",
            "volume": 42,
            "muted": False,
            "enabled": True,
            "input": ["input-airplay"],
            "active_input": None,
        },
        hub,
    )
    zone._juke.inputs = {
        "input-airplay": {
            "input_id": "input-airplay",
            "input_class": 2,
            "input_type": "Airplay2",
            "enabled": True,
            "streaming": False,
        }
    }

    with pytest.raises(
        HomeAssistantError,
        match="not routed to zone Greatroom; enable its route before selecting it",
    ):
        await zone.async_select_source("Juke-DLNA2")

    assert hub.calls == []
