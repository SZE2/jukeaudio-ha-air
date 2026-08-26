"""Tests for the Juke zone media-player entities."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.components.media_player import MediaPlayerEntityFeature, MediaPlayerState

from custom_components.jukeaudio_ha.airplay import dump_airplay_targets, load_airplay_targets
from custom_components.jukeaudio_ha.airplay_helper import (
    CONF_AIRPLAY_TARGETS,
    CONF_HELPER_BASE_URL,
    CONF_HELPER_BEARER_TOKEN,
)
from custom_components.jukeaudio_ha.media_player import Zone


ZONE_ID = "zone-1"


class _FakeZoneHub:
    def __init__(self):
        self.calls = []

    async def set_zone_mute(self, zone_id, muted):
        self.calls.append(("set_zone_mute", zone_id, muted))

    async def set_zone_volume(self, zone_id, volume):
        self.calls.append(("set_zone_volume", zone_id, volume))


class _FakeResponse:
    status = 202

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return None

    async def json(self):
        return {"job_id": "opaque-job", "status": "running"}


class _FakeSession:
    def __init__(self):
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return _FakeResponse()


def _make_zone(zone_data, hub=None, *, zone_id=ZONE_ID, config_entry=None):
    """Build a zone entity around the coordinator cache shape."""
    juke = SimpleNamespace(
        zones={zone_id: zone_data},
        inputs={},
        hub=hub or SimpleNamespace(),
    )
    return Zone(juke, SimpleNamespace(), config_entry, zone_id)


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


def test_zone_advertises_play_media_only_for_exact_raop_mapping():
    """Only a valid explicit RAOP mapping enables direct helper playback."""
    config_entry = SimpleNamespace(
        options={
            CONF_HELPER_BASE_URL: "https://helper.example",
            CONF_HELPER_BEARER_TOKEN: "fixture-token",
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
        {CONF_HELPER_BASE_URL: "https://helper.example", CONF_HELPER_BEARER_TOKEN: "fixture-token", CONF_AIRPLAY_TARGETS: []},
        {CONF_HELPER_BASE_URL: "https://helper.example/path", CONF_HELPER_BEARER_TOKEN: "fixture-token", CONF_AIRPLAY_TARGETS: {}},
    ],
)
def test_zone_hides_play_media_when_helper_options_are_not_valid(options):
    """Incomplete or malformed options keep a zone control-only."""
    zone = _make_zone(
        {"name": "Living Room", "volume": 42, "muted": False, "enabled": True, "active_input": None},
        zone_id=ZONE_ID,
        config_entry=SimpleNamespace(options=options),
    )

    assert not zone.supported_features & MediaPlayerEntityFeature.PLAY_MEDIA


@pytest.mark.asyncio
async def test_zone_play_media_uses_helper_without_mutating_juke(monkeypatch):
    """Direct playback forwards the exact URL and leaves Juke state untouched."""
    session = _FakeSession()
    monkeypatch.setattr(
        "custom_components.jukeaudio_ha.airplay_helper.async_get_clientsession",
        lambda hass: session,
    )
    config_entry = SimpleNamespace(
        options={
            CONF_HELPER_BASE_URL: "https://helper.example",
            CONF_HELPER_BEARER_TOKEN: "fixture-token",
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
    zone.hass = SimpleNamespace()
    before = dict(zone._juke.zones[ZONE_ID])

    await zone.async_play_media("audio/mpeg", "https://media.example/exact.mp3")

    assert session.calls == [
        (
            "https://helper.example/v1/streams",
            {
                "json": {
                    "zone_id": "zone-1",
                    "media_url": "https://media.example/exact.mp3",
                },
                "headers": {"Authorization": "Bearer fixture-token"},
            },
        )
    ]
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

    assert disabled_zone.state is MediaPlayerState.OFF
    assert muted_zone.state is MediaPlayerState.PLAYING
