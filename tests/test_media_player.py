"""Tests for the Juke zone media-player entities."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.components.media_player import MediaPlayerEntityFeature, MediaPlayerState

from custom_components.jukeaudio_ha.media_player import Zone


ZONE_ID = "zone-1"


class _FakeZoneHub:
    def __init__(self):
        self.calls = []

    async def set_zone_mute(self, zone_id, muted):
        self.calls.append(("set_zone_mute", zone_id, muted))

    async def set_zone_volume(self, zone_id, volume):
        self.calls.append(("set_zone_volume", zone_id, volume))


def _make_zone(zone_data, hub=None):
    """Build a zone entity around the coordinator cache shape."""
    juke = SimpleNamespace(
        zones={ZONE_ID: zone_data},
        inputs={},
        hub=hub or SimpleNamespace(),
    )
    return Zone(juke, SimpleNamespace(), None, ZONE_ID)


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
