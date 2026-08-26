"""Offline contract tests for the isolated legacy RAOP helper."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import airplay_helper.sender as sender_module
from airplay_helper import (
    AirPlayMappingError,
    RaopSender,
    load_airplay_targets,
    load_targets_json,
    resolve_raop_target,
)


def _record(
    *,
    zone_id: str = "zone-6",
    host: str = "198.51.100.24",
    port: int = 7015,
    protocol_mode: str = "raop_fallback",
    **overrides: object,
) -> dict[str, object]:
    record: dict[str, object] = {
        "zone_id": zone_id,
        "host": host,
        "port": port,
        "device_id": "AA:BB:CC:DD:EE:06",
        "player_uuid": "player-zone-6",
        "service_name": "Zone 6 Receiver",
        "txt": {
            "deviceid": "AA:BB:CC:DD:EE:06",
            "ch": "2",
            "cn": "0,1",
            "sr": "44100",
            "not_raop": "must-not-be-forwarded",
        },
        "protocol_mode": protocol_mode,
    }
    record.update(overrides)
    return record


class FakeManualService:
    calls: list["FakeManualService"] = []

    def __init__(
        self,
        protocol: object,
        port: int,
        *,
        properties: dict[str, str] | None = None,
        credentials: str | None = None,
    ) -> None:
        self.protocol = protocol
        self.port = port
        self.properties = properties
        self.credentials = credentials
        self.__class__.calls.append(self)


class FakeAppleTV:
    instances: list["FakeAppleTV"] = []

    def __init__(self, address: str, name: str) -> None:
        self.address = address
        self.name = name
        self.services: list[FakeManualService] = []
        self.__class__.instances.append(self)

    def add_service(self, service: FakeManualService) -> None:
        self.services.append(service)


class FakeAudio:
    def __init__(self, receiver: "FakeReceiver") -> None:
        self.receiver = receiver

    async def stream_file(self, source: object) -> None:
        self.receiver.stream_sources.append(source)
        if self.receiver.stream_error is not None:
            raise self.receiver.stream_error


class FakeReceiver:
    def __init__(self, stream_error: BaseException | None = None) -> None:
        self.stream_error = stream_error
        self.stream_sources: list[object] = []
        self.audio = FakeAudio(self)
        self.closed = False
        self.close_error: BaseException | None = None

    async def close(self) -> None:
        self.closed = True
        if self.close_error is not None:
            raise self.close_error


class FakePyatv:
    class Protocol:
        RAOP = object()

    def __init__(self, receiver: FakeReceiver) -> None:
        self.receiver = receiver
        self.configs: list[FakeAppleTV] = []
        self.interface = SimpleNamespace()
        self.conf = SimpleNamespace(
            AppleTV=self._apple_tv,
            ManualService=FakeManualService,
        )
        self.const = SimpleNamespace(Protocol=self.Protocol)

    def _apple_tv(self, address: str, name: str) -> FakeAppleTV:
        config = FakeAppleTV(address, name)
        self.configs.append(config)
        return config

    async def connect(self, config: FakeAppleTV) -> FakeReceiver:
        return self.receiver


def _install_fake_pyatv(monkeypatch: pytest.MonkeyPatch, receiver: FakeReceiver) -> FakePyatv:
    fake = FakePyatv(receiver)
    monkeypatch.setattr(sender_module, "_load_pyatv", lambda: fake)
    FakeManualService.calls.clear()
    FakeAppleTV.instances.clear()
    return fake


def test_json_loader_is_strict_and_preserves_immutable_explicit_mapping() -> None:
    payload = json.dumps({"zone-6": _record()})

    targets = load_targets_json(payload)

    assert len(targets) == 1
    assert targets[0].zone_id == "zone-6"
    assert targets[0].host == "198.51.100.24"
    with pytest.raises(TypeError):
        targets[0].txt["new"] = "value"  # type: ignore[index]
    with pytest.raises(AirPlayMappingError, match="JSON object"):
        load_targets_json("[]")
    with pytest.raises(AirPlayMappingError, match="valid JSON"):
        load_targets_json("not-json")


def test_json_loader_rejects_duplicate_keys_and_unknown_record_fields() -> None:
    record = json.dumps(_record(), separators=(",", ":"))[1:-1]
    duplicate_payload = '{"zone-6": {' + record + '}, "zone-6": {' + record + '}}'

    with pytest.raises(AirPlayMappingError, match="duplicate"):
        load_targets_json(duplicate_payload)
    with pytest.raises(AirPlayMappingError, match="invalid shape"):
        load_airplay_targets({"zone-6": _record(password="not-stored")})


def test_resolve_raop_target_rejects_unknown_zone_without_name_or_ip_inference() -> None:
    targets = load_airplay_targets({"zone-6": _record()})

    for supplied_id in ("Zone 6 Receiver", "198.51.100.24", "player-zone-6"):
        with pytest.raises(AirPlayMappingError, match="Unknown zone_id"):
            resolve_raop_target(targets, supplied_id)


def test_resolve_raop_target_rejects_airplay2_mode() -> None:
    targets = load_airplay_targets(
        {"zone-6": _record(protocol_mode="airplay2")}
    )

    with pytest.raises(AirPlayMappingError, match="raop_fallback"):
        resolve_raop_target(targets, "zone-6")


@pytest.mark.asyncio
async def test_sender_uses_only_exact_zone_mapping_and_raop_txt(monkeypatch: pytest.MonkeyPatch) -> None:
    receiver = FakeReceiver()
    fake = _install_fake_pyatv(monkeypatch, receiver)
    targets = load_airplay_targets(
        {
            "zone-6": _record(),
            "zone-7": _record(
                zone_id="zone-7",
                host="198.51.100.25",
                port=7016,
                service_name="Zone 7 Receiver",
                device_id="AA:BB:CC:DD:EE:07",
                player_uuid="player-zone-7",
            ),
        }
    )

    await RaopSender().stream_wav(resolve_raop_target(targets, "zone-6"), "exact.wav")

    config = fake.configs[0]
    service = config.services[0]
    assert config.address == "198.51.100.24"
    assert service.port == 7015
    assert service.protocol is fake.Protocol.RAOP
    assert service.properties == {
        "deviceid": "AA:BB:CC:DD:EE:06",
        "ch": "2",
        "cn": "0,1",
        "sr": "44100",
    }
    assert receiver.stream_sources == ["exact.wav"]


@pytest.mark.asyncio
async def test_sender_propagates_stream_failure_and_still_closes(monkeypatch: pytest.MonkeyPatch) -> None:
    receiver = FakeReceiver(stream_error=RuntimeError("stream failed"))
    _install_fake_pyatv(monkeypatch, receiver)
    target = resolve_raop_target(load_airplay_targets({"zone-6": _record()}), "zone-6")

    with pytest.raises(RuntimeError, match="stream failed"):
        await RaopSender().stream_wav(target, "failed.wav")

    assert receiver.closed is True


@pytest.mark.asyncio
async def test_sender_tolerates_remote_close_only_during_completed_teardown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receiver = FakeReceiver()
    receiver.close_error = ConnectionResetError("receiver closed control connection")
    _install_fake_pyatv(monkeypatch, receiver)
    target = resolve_raop_target(load_airplay_targets({"zone-6": _record()}), "zone-6")

    await RaopSender().stream_wav(target, "completed.wav")

    assert receiver.stream_sources == ["completed.wav"]
    assert receiver.closed is True


@pytest.mark.asyncio
async def test_sender_does_not_hide_stream_error_when_teardown_also_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receiver = FakeReceiver(stream_error=RuntimeError("setup or stream failed"))
    receiver.close_error = ConnectionResetError("receiver closed early")
    _install_fake_pyatv(monkeypatch, receiver)
    target = resolve_raop_target(load_airplay_targets({"zone-6": _record()}), "zone-6")

    with pytest.raises(RuntimeError, match="setup or stream failed"):
        await RaopSender().stream_wav(target, "not-completed.wav")

    assert receiver.closed is True
