"""Component-boundary contracts for integrated direct RAOP playback."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from homeassistant import config_entries

from custom_components.jukeaudio_ha import airplay
from custom_components.jukeaudio_ha.config_flow import ConfigFlow


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _record(
    *,
    zone_id: str = "zone-1",
    protocol_mode: str = "raop_fallback",
    txt: dict[str, str] | None = None,
) -> dict[str, object]:
    return {
        "zone_id": zone_id,
        "host": "receiver.example",
        "port": 7000,
        "device_id": "AA:BB:CC:DD:EE:01",
        "player_uuid": "player-1",
        "service_name": "Living Receiver",
        "txt": txt or {"deviceid": "AA:BB:CC:DD:EE:01", "sr": "44100"},
        "protocol_mode": protocol_mode,
    }


def _entry(options: object | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        entry_id="entry-1",
        data={
            "host": "juke.example",
            "username": "Admin",
            "password": "fixture-password",
            "scan_interval": 30,
        },
        options={} if options is None else options,
    )


def test_manifest_declares_pure_python_raop_runtime_dependency() -> None:
    manifest = json.loads(
        (REPOSITORY_ROOT / "custom_components/jukeaudio_ha/manifest.json").read_text()
    )

    assert "pyatv==0.18.0" in manifest["requirements"]


def test_options_flow_exposes_only_integrated_raop_mapping() -> None:
    flow = ConfigFlow.async_get_options_flow(_entry())

    result = flow._schema()  # noqa: SLF001 - inspect the component boundary schema
    fields = {key.schema for key in result.schema}

    assert fields == {"airplay_targets"}


def test_component_translation_surface_has_no_legacy_helper_options() -> None:
    """The HACS UI exposes only the integrated target mapping option."""
    component_root = REPOSITORY_ROOT / "custom_components/jukeaudio_ha"
    for translation in (component_root / "strings.json", *sorted((component_root / "translations").glob("*.json"))):
        text = translation.read_text()
        assert "helper_base_url" not in text
        assert "helper_bearer_token" not in text
        assert "RAOP helper" not in text


def test_separate_helper_runtime_is_not_shipped() -> None:
    """The HACS deliverable contains no separate helper runtime."""
    component_root = REPOSITORY_ROOT / "custom_components/jukeaudio_ha"
    assert not (REPOSITORY_ROOT / "airplay_helper").exists()
    assert not (component_root / "airplay_helper.py").exists()


@pytest.mark.parametrize(
    "media_url",
    [
        "file:///tmp/audio.mp3",
        "http://localhost/audio.mp3",
        "http://127.0.0.1/audio.mp3",
        "http://2130706433/audio.mp3",
        "http://127.000.000.001/audio.mp3",
        "http://127.1/audio.mp3",
        "http://127.0.1/audio.mp3",
        "http://0177.0.0.1/audio.mp3",
        "http://0x7f.0.0.1/audio.mp3",
        "http://[::1]/audio.mp3",
        "http://[::ffff:127.0.0.1]/audio.mp3",
        "https://user:password@media.example/audio.mp3",
        "https://media.example:99999/audio.mp3",
    ],
)
def test_direct_sender_rejects_unsafe_media_urls_before_loading_pyatv(media_url: str) -> None:
    assert hasattr(airplay, "validate_media_url")

    with pytest.raises(airplay.AirPlayPlaybackError, match="invalid media URL"):
        airplay.validate_media_url(media_url)


class _FakeManualService:
    calls: list["_FakeManualService"] = []

    def __init__(
        self,
        identifier: str,
        protocol: object,
        port: int,
        properties: dict[str, str],
    ) -> None:
        self.identifier = identifier
        self.protocol = protocol
        self.port = port
        self.properties = properties
        self.__class__.calls.append(self)


class _FakeAppleTV:
    def __init__(self, address: str, name: str) -> None:
        self.address = address
        self.name = name
        self.services: list[_FakeManualService] = []

    def add_service(self, service: _FakeManualService) -> None:
        self.services.append(service)


class _FakeStream:
    def __init__(self, receiver: "_FakeReceiver") -> None:
        self.receiver = receiver

    async def stream_file(self, source: str) -> None:
        self.receiver.sources.append(source)
        self.receiver.started.set()
        if self.receiver.stream_error is not None:
            raise self.receiver.stream_error
        await self.receiver.release.wait()


class _FakeReceiver:
    def __init__(self, *, stream_error: BaseException | None = None) -> None:
        import asyncio

        self.sources: list[str] = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.closed = False
        self.stream_error = stream_error
        self.stream = _FakeStream(self)

    def close(self) -> list[object]:
        async def finish() -> None:
            self.closed = True

        return [finish()]


class _FakePyatv:
    class Protocol:
        RAOP = object()

    def __init__(self, receiver: _FakeReceiver) -> None:
        self.receiver = receiver
        self.configs: list[_FakeAppleTV] = []
        self.conf = SimpleNamespace(
            AppleTV=self._apple_tv,
            ManualService=_FakeManualService,
        )
        self.const = SimpleNamespace(Protocol=self.Protocol)

    def _apple_tv(self, address: str, name: str) -> _FakeAppleTV:
        config = _FakeAppleTV(address, name)
        self.configs.append(config)
        return config

    async def connect(self, config: _FakeAppleTV, loop: object) -> _FakeReceiver:
        return self.receiver


def test_direct_sender_is_integrated_and_not_a_legacy_client() -> None:
    assert hasattr(airplay, "DirectRaopClient")
    assert not hasattr(airplay, "AirPlayHelperClient")


@pytest.mark.asyncio
async def test_direct_sender_streams_exact_url_with_explicit_raop_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receiver = _FakeReceiver()
    receiver.release.set()
    fake = _FakePyatv(receiver)
    monkeypatch.setattr(airplay, "_load_pyatv", lambda: fake)
    entry = _entry(
        {
            "airplay_targets": {"zone-1": _record()},
        }
    )

    await airplay.DirectRaopClient(entry).async_play_media(
        "zone-1", "https://media.example/exact.mp3"
    )

    service = fake.configs[0].services[0]
    assert fake.configs[0].address == "receiver.example"
    assert service.identifier == "raop:AA:BB:CC:DD:EE:01:player-1:7000"
    assert service.protocol is fake.Protocol.RAOP
    assert service.properties == {"deviceid": "AA:BB:CC:DD:EE:01", "sr": "44100"}
    assert receiver.sources == ["https://media.example/exact.mp3"]
    assert receiver.closed is True


@pytest.mark.asyncio
async def test_direct_sender_does_not_swallow_pretransfer_shairport_teardown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receiver = _FakeReceiver(
        stream_error=RuntimeError("not connected to remote")
    )
    fake = _FakePyatv(receiver)
    monkeypatch.setattr(airplay, "_load_pyatv", lambda: fake)
    entry = _entry(
        {
            "airplay_targets": {
                "zone-1": _record(
                    txt={
                        "deviceid": "AA:BB:CC:DD:EE:01",
                        "model": "Shairport Sync",
                    }
                )
            }
        }
    )

    with pytest.raises((airplay.AirPlayPlaybackError, RuntimeError)) as exc_info:
        await airplay.DirectRaopClient(entry).async_play_media(
            "zone-1", "https://media.example/pretransfer.mp3"
        )

    if isinstance(exc_info.value, RuntimeError):
        assert str(exc_info.value) == "not connected to remote"
    assert receiver.closed is True


@pytest.mark.asyncio
async def test_direct_sender_requires_exact_zone_and_raop_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_loaded() -> object:
        raise AssertionError("pyatv must not load for an unapproved target")

    monkeypatch.setattr(airplay, "_load_pyatv", fail_if_loaded)
    entry = _entry(
        {
            "airplay_targets": {
                "zone-1": _record(protocol_mode="airplay2"),
            },
        }
    )

    with pytest.raises(airplay.AirPlayPlaybackError, match="not configured"):
        await airplay.DirectRaopClient(entry).async_play_media(
            "zone-1", "https://media.example/exact.mp3"
        )


@pytest.mark.asyncio
async def test_direct_sender_cancellation_closes_receiver_and_remains_cancellable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    receiver = _FakeReceiver()
    fake = _FakePyatv(receiver)
    monkeypatch.setattr(airplay, "_load_pyatv", lambda: fake)
    entry = _entry({"airplay_targets": {"zone-1": _record()}})
    task = asyncio.create_task(
        airplay.DirectRaopClient(entry).async_play_media(
            "zone-1", "https://media.example/exact.mp3"
        )
    )

    await receiver.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert receiver.closed is True


@pytest.mark.asyncio
async def test_options_flow_preserves_unrelated_options_and_discards_legacy_helper_values() -> None:
    flow = ConfigFlow.async_get_options_flow(
        _entry(
            {
                "helper_base_url": "https://old-helper.example",
                "helper_bearer_token": "fixture-token",
                "airplay_targets": {},
                "unrelated_option": "preserved",
            }
        )
    )

    result = await flow.async_step_init(
        {"airplay_targets": json.dumps({"zone-1": _record()})}
    )

    assert result["type"] == "create_entry"
    assert result["data"] == {
        "airplay_targets": {"zone-1": _record()},
        "unrelated_option": "preserved",
    }


def test_json_serialized_options_mapping_enables_exact_raop_zone() -> None:
    """HA option storage may return the Options-flow JSON field as text."""
    entry = _entry({"airplay_targets": json.dumps({"zone-1": _record()})})

    assert airplay.has_raop_target(entry, "zone-1") is True
    assert airplay.load_raop_config(entry).target_for_zone("zone-1") is not None


@pytest.mark.asyncio
async def test_raop_sender_rejects_unsafe_url_before_loading_pyatv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = airplay.load_airplay_targets({"zone-1": _record()})[0]

    def fail_if_loaded() -> object:
        raise AssertionError("pyatv must not load for an unsafe media URL")

    monkeypatch.setattr(airplay, "_load_pyatv", fail_if_loaded)

    with pytest.raises(airplay.AirPlayPlaybackError, match="invalid media URL"):
        await airplay.RaopSender().stream_url(target, "file:///tmp/audio.mp3")


@pytest.mark.asyncio
async def test_raop_sender_rejects_oversized_numeric_hostname_before_loading_pyatv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = airplay.load_airplay_targets({"zone-1": _record()})[0]
    loaded = False

    def fail_if_loaded() -> object:
        nonlocal loaded
        loaded = True
        raise AssertionError("pyatv must not load for an invalid media URL")

    monkeypatch.setattr(airplay, "_load_pyatv", fail_if_loaded)
    media_url = "http://" + ("9" * 5000) + "/audio"

    with pytest.raises(airplay.AirPlayPlaybackError, match="invalid media URL"):
        await airplay.RaopSender().stream_url(target, media_url)

    assert loaded is False
