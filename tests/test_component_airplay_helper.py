"""Tests for the component-side guarded RAOP helper client."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.jukeaudio_ha.airplay import dump_airplay_targets, load_airplay_targets
from custom_components.jukeaudio_ha.airplay_helper import (
    CONF_AIRPLAY_TARGETS,
    CONF_HELPER_BASE_URL,
    CONF_HELPER_BEARER_TOKEN,
    AirPlayHelperError,
    AirPlayHelperClient,
    has_raop_target,
    load_airplay_helper_config,
)


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
        self.calls: list[tuple[str, dict[str, object]]] = []

    def post(self, url: str, **kwargs: object) -> _FakeResponse:
        self.calls.append((url, kwargs))
        return _FakeResponse()


class _ConfigurableResponse(_FakeResponse):
    def __init__(self, status: int, payload: object) -> None:
        self.status = status
        self._payload = payload

    async def json(self):
        return self._payload


class _ConfigurableSession:
    def __init__(self, response: _ConfigurableResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, object]]] = []

    def post(self, url: str, **kwargs: object) -> _ConfigurableResponse:
        self.calls.append((url, kwargs))
        return self.response


class _ExplodingSession:
    def post(self, url: str, **kwargs: object):
        raise RuntimeError("fixture-network-error-with-token")


def _options(*, targets: object | None = None, base_url: object = "https://helper.example"):
    return {
        CONF_HELPER_BASE_URL: base_url,
        CONF_HELPER_BEARER_TOKEN: "fixture-token",
        CONF_AIRPLAY_TARGETS: (
            dump_airplay_targets(load_airplay_targets({"zone-1": _record()}))
            if targets is None
            else targets
        ),
    }


@pytest.mark.asyncio
async def test_client_posts_exact_explicit_zone_media_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _FakeSession()
    monkeypatch.setattr(
        "custom_components.jukeaudio_ha.airplay_helper.async_get_clientsession",
        lambda hass: session,
    )
    entry = SimpleNamespace(
        options={
            CONF_HELPER_BASE_URL: "https://helper.example/",
            CONF_HELPER_BEARER_TOKEN: "fixture-token",
            CONF_AIRPLAY_TARGETS: dump_airplay_targets(
                load_airplay_targets({"zone-1": _record()})
            ),
        }
    )

    job_id = await AirPlayHelperClient(SimpleNamespace(), entry).async_play_media(
        "zone-1", "https://media.example/audio.mp3"
    )

    assert job_id == "opaque-job"
    assert session.calls == [
        (
            "https://helper.example/v1/streams",
            {
                "json": {
                    "zone_id": "zone-1",
                    "media_url": "https://media.example/audio.mp3",
                },
                "headers": {"Authorization": "Bearer fixture-token"},
            },
        )
    ]


@pytest.mark.parametrize(
    "options",
    [
        {},
        {CONF_HELPER_BASE_URL: "https://helper.example"},
        {CONF_HELPER_BEARER_TOKEN: "fixture-token", CONF_AIRPLAY_TARGETS: {}},
        _options(base_url="https://helper.example/path"),
        _options(targets=[]),
    ],
)
def test_invalid_or_incomplete_options_fail_closed(options: object) -> None:
    """Only complete explicit options produce a usable helper config."""
    entry = SimpleNamespace(options=options)

    assert load_airplay_helper_config(entry) is None
    assert has_raop_target(entry, "zone-1") is False


def test_helper_configuration_never_reads_juke_connection_data() -> None:
    """Helper settings in normal Juke entry data cannot enable playback."""
    entry = SimpleNamespace(options={}, data=_options())

    assert load_airplay_helper_config(entry) is None
    assert has_raop_target(entry, "zone-1") is False


@pytest.mark.parametrize(
    "media_url",
    [
        "file:///tmp/audio.mp3",
        "http://localhost/audio.mp3",
        "http://127.0.0.1/audio.mp3",
        "http://2130706433/audio.mp3",
        "http://127.000.000.001/audio.mp3",
        "http://[::1]/audio.mp3",
        "http://[::ffff:127.0.0.1]/audio.mp3",
        "https://user:password@media.example/audio.mp3",
        "https://media.example:99999/audio.mp3",
    ],
)
@pytest.mark.asyncio
async def test_invalid_media_urls_are_rejected_before_network(
    monkeypatch: pytest.MonkeyPatch, media_url: str
) -> None:
    """The component validates direct URLs and never retrieves them locally."""
    session = _FakeSession()
    monkeypatch.setattr(
        "custom_components.jukeaudio_ha.airplay_helper.async_get_clientsession",
        lambda hass: session,
    )
    entry = SimpleNamespace(options=_options())

    with pytest.raises(AirPlayHelperError, match="invalid media URL"):
        await AirPlayHelperClient(SimpleNamespace(), entry).async_play_media(
            "zone-1", media_url
        )

    assert session.calls == []


@pytest.mark.parametrize(
    ("status", "payload"),
    [
        (400, {"error": "body-must-not-escape"}),
        (202, {"job_id": "opaque-job", "status": "queued"}),
        (202, {"job_id": "", "status": "running"}),
        (202, {"job_id": "opaque-job"}),
    ],
)
@pytest.mark.asyncio
async def test_malformed_helper_responses_are_sanitized(
    monkeypatch: pytest.MonkeyPatch, status: int, payload: object
) -> None:
    """Unexpected helper responses fail without exposing response or token data."""
    response = _ConfigurableResponse(status, payload)
    session = _ConfigurableSession(response)
    monkeypatch.setattr(
        "custom_components.jukeaudio_ha.airplay_helper.async_get_clientsession",
        lambda hass: session,
    )
    entry = SimpleNamespace(options=_options())

    with pytest.raises(AirPlayHelperError) as caught:
        await AirPlayHelperClient(SimpleNamespace(), entry).async_play_media(
            "zone-1", "https://media.example/audio.mp3"
        )

    assert "body-must-not-escape" not in str(caught.value)
    assert "fixture-token" not in str(caught.value)
    assert session.calls


@pytest.mark.asyncio
async def test_helper_network_errors_are_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    """Transport errors do not leak their raw exception text or cause."""
    monkeypatch.setattr(
        "custom_components.jukeaudio_ha.airplay_helper.async_get_clientsession",
        lambda hass: _ExplodingSession(),
    )
    entry = SimpleNamespace(options=_options())

    with pytest.raises(AirPlayHelperError) as caught:
        await AirPlayHelperClient(SimpleNamespace(), entry).async_play_media(
            "zone-1", "https://media.example/audio.mp3"
        )

    assert str(caught.value) == "AirPlay helper playback request failed"
    assert "fixture-network-error-with-token" not in str(caught.value)
    assert caught.value.__cause__ is None


@pytest.mark.parametrize(
    "base_url",
    [
        "https://user:password@helper.example",
        "https://helper.example/path",
        "https://helper.example?query=blocked",
        "https://helper.example?",
        "https://helper.example#fragment",
        "https://helper.example#",
        "ftp://helper.example",
    ],
)
def test_helper_origin_requires_http_absolute_root_without_userinfo(base_url: str) -> None:
    """Helper configuration accepts only an HTTP(S) origin."""
    assert load_airplay_helper_config(SimpleNamespace(options=_options(base_url=base_url))) is None


@pytest.mark.asyncio
async def test_invalid_options_fail_with_sanitized_playback_error() -> None:
    """A caller gets a fixed error instead of an implicit loopback fallback."""
    entry = SimpleNamespace(options={})

    with pytest.raises(AirPlayHelperError, match="not configured") as caught:
        # The invalid URL is intentionally not reached when helper options are absent.
        await AirPlayHelperClient(SimpleNamespace(), entry).async_play_media(
            "zone-1", "https://media.example/audio.mp3"
        )
    assert "localhost" not in str(caught.value)
