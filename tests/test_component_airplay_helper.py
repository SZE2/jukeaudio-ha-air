"""Component-side tests for integrated direct RAOP playback."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.jukeaudio_ha.airplay import (
    AirPlayPlaybackError,
    DirectRaopClient,
    dump_airplay_targets,
    has_raop_target,
    load_airplay_targets,
)
from custom_components.jukeaudio_ha.const import CONF_AIRPLAY_TARGETS


def _record(*, zone_id: str = "zone-1", protocol_mode: str = "raop_fallback") -> dict[str, object]:
    return {
        "zone_id": zone_id,
        "host": "receiver.example",
        "port": 7000,
        "device_id": "AA:BB:CC:DD:EE:01",
        "player_uuid": "player-1",
        "service_name": "Living Receiver",
        "txt": {"deviceid": "AA:BB:CC:DD:EE:01"},
        "protocol_mode": protocol_mode,
    }


def _entry(options: object) -> SimpleNamespace:
    return SimpleNamespace(options=options)


def test_invalid_or_incomplete_raop_options_fail_closed() -> None:
    """Only a valid serialized target mapping advertises direct playback."""
    options_list = [
        {},
        {CONF_AIRPLAY_TARGETS: []},
        {CONF_AIRPLAY_TARGETS: {"zone-1": {"zone_id": "wrong"}}},
        {CONF_AIRPLAY_TARGETS: {"zone-1": _record(protocol_mode="airplay2")}},
    ]

    for options in options_list:
        entry = _entry(options)
        assert has_raop_target(entry, "zone-1") is False


def test_raop_configuration_never_reads_juke_connection_data() -> None:
    """Connection data cannot implicitly enable a direct target."""
    entry = _entry({})
    entry.data = {
        "airplay_targets": {"zone-1": _record()},
        "host": "juke.example",
    }

    assert has_raop_target(entry, "zone-1") is False


@pytest.mark.parametrize(
    "media_url",
    [
        "file:///tmp/audio.mp3",
        "http://localhost/audio.mp3",
        "http://127.0.0.1/audio.mp3",
        "http://2130706433/audio.mp3",
        "http://127.1/audio.mp3",
        "http://0177.0.0.1/audio.mp3",
        "http://0x7f.0.0.1/audio.mp3",
        "http://[::1]/audio.mp3",
        "http://[::ffff:127.0.0.1]/audio.mp3",
        "https://user:password@media.example/audio.mp3",
        "https://media.example:99999/audio.mp3",
    ],
)
@pytest.mark.asyncio
async def test_invalid_media_urls_are_rejected_before_sender(
    media_url: str,
) -> None:
    """Unsafe direct URLs fail closed before any sender work is scheduled."""
    sender = AsyncMock()
    entry = _entry(
        {
            CONF_AIRPLAY_TARGETS: dump_airplay_targets(
                load_airplay_targets({"zone-1": _record()})
            )
        }
    )

    with pytest.raises(AirPlayPlaybackError, match="invalid media URL"):
        await DirectRaopClient(entry, sender_factory=lambda: sender).async_play_media(
            "zone-1", media_url
        )

    sender.stream_url.assert_not_awaited()


@pytest.mark.asyncio
async def test_direct_client_uses_only_exact_zone_target_and_url() -> None:
    """The direct client passes only the exact configured target and URL onward."""
    sender = AsyncMock()
    target = load_airplay_targets({"zone-1": _record()})[0]
    entry = _entry({CONF_AIRPLAY_TARGETS: dump_airplay_targets((target,))})

    await DirectRaopClient(entry, sender_factory=lambda: sender).async_play_media(
        "zone-1", "https://media.example/audio.mp3"
    )

    sender.stream_url.assert_awaited_once_with(target, "https://media.example/audio.mp3")
