"""Offline contract tests for the isolated legacy RAOP helper."""

from __future__ import annotations

import asyncio
import inspect
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
        identifier: str,
        protocol: object,
        port: int,
        properties: dict[str, str],
        credentials: str | None = None,
        password: str | None = None,
    ) -> None:
        self.identifier = identifier
        self.protocol = protocol
        self.port = port
        self.properties = properties
        self.credentials = credentials
        self.password = password
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


class FakeStream:
    def __init__(self, receiver: "FakeReceiver") -> None:
        self.receiver = receiver

    async def stream_file(self, source: object) -> None:
        self.receiver.stream_sources.append(source)
        if self.receiver.stream_error is not None:
            if self.receiver.mark_stream_complete_before_error:
                self.receiver.stream_transfer_completed = True
            raise self.receiver.stream_error
        self.receiver.stream_transfer_completed = True


class FakeReceiver:
    def __init__(self, stream_error: BaseException | None = None) -> None:
        self.stream_error = stream_error
        self.mark_stream_complete_before_error = False
        self.stream_transfer_completed = False
        self.stream_sources: list[object] = []
        self.stream = FakeStream(self)
        self.closed = False
        self.close_completed_tasks: set[int] = set()
        self.close_task_count = 1
        self.close_call_error: BaseException | None = None
        self.close_error: BaseException | None = None

    def close(self) -> list[asyncio.Task[None]]:
        if self.close_call_error is not None:
            raise self.close_call_error

        async def finish_close(index: int) -> None:
            await asyncio.sleep(0)
            self.closed = True
            self.close_completed_tasks.add(index)
            if self.close_error is not None and index == 0:
                raise self.close_error

        return [
            asyncio.create_task(finish_close(index))
            for index in range(self.close_task_count)
        ]

    @property
    def close_completed(self) -> bool:
        return len(self.close_completed_tasks) == self.close_task_count


class FakePyatv:
    class Protocol:
        RAOP = object()

    def __init__(self, receiver: FakeReceiver) -> None:
        self.receiver = receiver
        self.configs: list[FakeAppleTV] = []
        self.connect_loops: list[asyncio.AbstractEventLoop] = []
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

    async def connect(
        self,
        config: FakeAppleTV,
        loop: asyncio.AbstractEventLoop,
    ) -> FakeReceiver:
        assert loop is asyncio.get_running_loop()
        self.connect_loops.append(loop)
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
    receiver.close_task_count = 2
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
    assert service.identifier == (
        "raop:AA:BB:CC:DD:EE:06:player-zone-6:7015"
    )
    assert service.port == 7015
    assert service.protocol is fake.Protocol.RAOP
    assert service.properties == {
        "deviceid": "AA:BB:CC:DD:EE:06",
        "ch": "2",
        "cn": "0,1",
        "sr": "44100",
    }
    assert fake.connect_loops == [asyncio.get_running_loop()]
    assert receiver.stream_sources == ["exact.wav"]
    assert receiver.close_completed is True


@pytest.mark.asyncio
async def test_sender_smoke_uses_real_pyatv_api_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyatv = pytest.importorskip("pyatv")
    import pyatv.conf as pyatv_conf
    import pyatv.interface as pyatv_interface

    assert callable(getattr(pyatv_interface.Stream, "stream_file", None))
    assert not hasattr(pyatv_interface.Audio, "stream_file")

    manual_service_parameters = list(
        inspect.signature(pyatv_conf.ManualService).parameters
    )
    connect_parameters = list(inspect.signature(pyatv.connect).parameters)
    assert manual_service_parameters[:4] == [
        "identifier",
        "protocol",
        "port",
        "properties",
    ]
    assert connect_parameters[:2] == ["config", "loop"]
    close_signature = inspect.signature(pyatv_conf.AppleTV.close)
    assert not inspect.iscoroutinefunction(pyatv_conf.AppleTV.close)
    assert "Task" in str(close_signature.return_annotation)

    receiver = FakeReceiver()

    async def fake_connect(
        config: object,
        loop: asyncio.AbstractEventLoop,
    ) -> FakeReceiver:
        assert loop is asyncio.get_running_loop()
        return receiver

    monkeypatch.setattr(pyatv, "connect", fake_connect)
    target = resolve_raop_target(load_airplay_targets({"zone-6": _record()}), "zone-6")

    await RaopSender().stream_wav(target, "smoke.wav")

    assert receiver.stream_sources == ["smoke.wav"]
    assert receiver.closed is True
    assert receiver.close_completed is True


def test_real_pyatv_raop_source_contract_keeps_url_retrieval_in_pyatv() -> None:
    pytest.importorskip("pyatv")
    audio_source = pytest.importorskip("pyatv.protocols.raop.audio_source")
    from pyatv.interface import Stream

    open_source = getattr(audio_source, "open_source", None)
    assert callable(open_source)
    open_source_source = inspect.getsource(open_source)
    assert "if isinstance(source, str):" in open_source_source
    assert "InternetSource.open" in open_source_source
    assert "FileSource.open" in open_source_source

    source_parameter = next(
        parameter
        for name, parameter in inspect.signature(Stream.stream_file).parameters.items()
        if name != "self"
    )
    assert source_parameter.name == "file"
    assert "str" in str(source_parameter.annotation)


@pytest.mark.asyncio
async def test_sender_propagates_stream_failure_and_still_closes(monkeypatch: pytest.MonkeyPatch) -> None:
    receiver = FakeReceiver(stream_error=RuntimeError("stream failed"))
    _install_fake_pyatv(monkeypatch, receiver)
    target = resolve_raop_target(load_airplay_targets({"zone-6": _record()}), "zone-6")

    with pytest.raises(RuntimeError, match="stream failed"):
        await RaopSender().stream_wav(target, "failed.wav")

    assert receiver.closed is True
    assert receiver.close_completed is True


@pytest.mark.asyncio
async def test_sender_tolerates_pyatv_not_connected_teardown_after_completed_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receiver = FakeReceiver()
    receiver.close_error = RuntimeError("not connected to remote")
    _install_fake_pyatv(monkeypatch, receiver)
    target = resolve_raop_target(load_airplay_targets({"zone-6": _record()}), "zone-6")

    await RaopSender().stream_wav(target, "completed-pyatv.wav")

    assert receiver.stream_sources == ["completed-pyatv.wav"]
    assert receiver.closed is True
    assert receiver.close_completed is True


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
    assert receiver.close_completed is True


@pytest.mark.asyncio
async def test_sender_does_not_tolerate_remote_error_from_close_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receiver = FakeReceiver()
    receiver.close_call_error = ConnectionResetError("close call failed")
    _install_fake_pyatv(monkeypatch, receiver)
    target = resolve_raop_target(load_airplay_targets({"zone-6": _record()}), "zone-6")

    with pytest.raises(ConnectionResetError, match="close call failed"):
        await RaopSender().stream_wav(target, "close-call-error.wav")


@pytest.mark.asyncio
async def test_sender_does_not_tolerate_pyatv_runtime_error_from_close_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receiver = FakeReceiver()
    receiver.close_call_error = RuntimeError("not connected to remote")
    _install_fake_pyatv(monkeypatch, receiver)
    target = resolve_raop_target(load_airplay_targets({"zone-6": _record()}), "zone-6")

    with pytest.raises(RuntimeError, match="not connected to remote"):
        await RaopSender().stream_wav(target, "close-call-runtime-error.wav")


@pytest.mark.asyncio
async def test_sender_propagates_non_remote_close_task_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receiver = FakeReceiver()
    receiver.close_error = RuntimeError("teardown failed")
    _install_fake_pyatv(monkeypatch, receiver)
    target = resolve_raop_target(load_airplay_targets({"zone-6": _record()}), "zone-6")

    with pytest.raises(RuntimeError, match="teardown failed"):
        await RaopSender().stream_wav(target, "teardown-error.wav")

    assert receiver.close_completed is True


@pytest.mark.asyncio
async def test_sender_tolerates_shairport_stream_teardown_after_completed_transfer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receiver = FakeReceiver(stream_error=RuntimeError("not connected to remote"))
    _install_fake_pyatv(monkeypatch, receiver)
    target = resolve_raop_target(
        load_airplay_targets(
            {
                "zone-6": _record(
                    txt={"deviceid": "AA:BB:CC:DD:EE:06", "model": "Shairport Sync"}
                )
            }
        ),
        "zone-6",
    )

    await RaopSender().stream_wav(target, "completed-shairport.wav")

    assert receiver.stream_sources == ["completed-shairport.wav"]
    assert receiver.closed is True
    assert receiver.close_completed is True


@pytest.mark.asyncio
async def test_sender_requires_completion_marker_for_injected_pretransfer_teardown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receiver = FakeReceiver(stream_error=RuntimeError("not connected to remote"))
    receiver.mark_stream_complete_before_error = False
    _install_fake_pyatv(monkeypatch, receiver)
    target = resolve_raop_target(
        load_airplay_targets(
            {
                "zone-6": _record(
                    txt={"deviceid": "AA:BB:CC:DD:EE:06", "model": "Shairport Sync"}
                )
            }
        ),
        "zone-6",
    )

    with pytest.raises(RuntimeError, match="not connected to remote"):
        await RaopSender(
            transfer_complete_marker=lambda: receiver.stream_transfer_completed
        ).stream_wav(target, "not-completed-shairport.wav")

    assert receiver.closed is True
    assert receiver.close_completed is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model",
    [None, "Other Receiver"],
)
async def test_sender_propagates_stream_teardown_for_non_shairport_targets(
    monkeypatch: pytest.MonkeyPatch,
    model: str | None,
) -> None:
    receiver = FakeReceiver(stream_error=RuntimeError("not connected to remote"))
    _install_fake_pyatv(monkeypatch, receiver)
    txt = {"deviceid": "AA:BB:CC:DD:EE:06"}
    if model is not None:
        txt["model"] = model
    target = resolve_raop_target(
        load_airplay_targets({"zone-6": _record(txt=txt)}), "zone-6"
    )

    with pytest.raises(RuntimeError, match="not connected to remote"):
        await RaopSender().stream_wav(target, "wrong-receiver.wav")

    assert receiver.closed is True
    assert receiver.close_completed is True


@pytest.mark.asyncio
async def test_sender_propagates_other_stream_errors_for_shairport_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receiver = FakeReceiver(stream_error=RuntimeError("different stream failure"))
    _install_fake_pyatv(monkeypatch, receiver)
    target = resolve_raop_target(
        load_airplay_targets(
            {
                "zone-6": _record(
                    txt={"deviceid": "AA:BB:CC:DD:EE:06", "model": "Shairport Sync"}
                )
            }
        ),
        "zone-6",
    )

    with pytest.raises(RuntimeError, match="different stream failure"):
        await RaopSender().stream_wav(target, "other-stream-error.wav")


@pytest.mark.asyncio
async def test_sender_does_not_tolerate_connection_error_from_stream_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receiver = FakeReceiver(stream_error=ConnectionError("receiver disconnected"))
    _install_fake_pyatv(monkeypatch, receiver)
    target = resolve_raop_target(
        load_airplay_targets(
            {
                "zone-6": _record(
                    txt={"deviceid": "AA:BB:CC:DD:EE:06", "model": "Shairport Sync"}
                )
            }
        ),
        "zone-6",
    )

    with pytest.raises(ConnectionError, match="receiver disconnected"):
        await RaopSender().stream_wav(target, "connection-error.wav")


@pytest.mark.asyncio
async def test_sender_accepts_injected_completion_marker_before_shairport_teardown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receiver = FakeReceiver(stream_error=RuntimeError("not connected to remote"))
    receiver.mark_stream_complete_before_error = True
    _install_fake_pyatv(monkeypatch, receiver)
    target = resolve_raop_target(
        load_airplay_targets(
            {
                "zone-6": _record(
                    txt={"deviceid": "AA:BB:CC:DD:EE:06", "model": "Shairport Sync"}
                )
            }
        ),
        "zone-6",
    )

    await RaopSender(
        transfer_complete_marker=lambda: receiver.stream_transfer_completed
    ).stream_wav(target, "marked-completed-shairport.wav")

    assert receiver.stream_transfer_completed is True
    assert receiver.close_completed is True


@pytest.mark.asyncio
async def test_sender_does_not_hide_stream_error_when_teardown_also_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receiver = FakeReceiver(stream_error=RuntimeError("setup or stream failed"))
    receiver.close_error = RuntimeError("teardown failed after stream error")
    _install_fake_pyatv(monkeypatch, receiver)
    target = resolve_raop_target(load_airplay_targets({"zone-6": _record()}), "zone-6")

    with pytest.raises(RuntimeError, match="setup or stream failed"):
        await RaopSender().stream_wav(target, "not-completed.wav")

    assert receiver.closed is True
    assert receiver.close_completed is True
