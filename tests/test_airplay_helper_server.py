"""Offline contract tests for the isolated RAOP helper HTTP control plane."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

import airplay_helper.server as server_module
from airplay_helper.mapping import AirPlayTarget, dump_airplay_targets
from airplay_helper.server import TOKEN_ENV_VAR, build_parser, create_app, main


_TEST_TOKEN = "token-for-test-only"
_MEDIA_HOST = "media.example.test"


class FakeSender:
    def __init__(self) -> None:
        self.calls: list[tuple[AirPlayTarget, str]] = []

    async def stream_wav(self, target: AirPlayTarget, media_url: str) -> None:
        self.calls.append((target, media_url))


class BlockingSender(FakeSender):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.cancelled = False
        self.exited = asyncio.Event()

    async def stream_wav(self, target: AirPlayTarget, media_url: str) -> None:
        self.calls.append((target, media_url))
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        finally:
            self.exited.set()


class FailingSender(FakeSender):
    def __init__(self) -> None:
        super().__init__()
        self.finished = asyncio.Event()

    async def stream_wav(self, target: AirPlayTarget, media_url: str) -> None:
        self.calls.append((target, media_url))
        self.finished.set()
        raise RuntimeError("secret receiver and URL must not escape")


def _sender_factory(sender: FakeSender):
    return lambda: sender


def _target(*, zone_id: str = "zone-alpha", protocol_mode: str = "raop_fallback") -> AirPlayTarget:
    suffix = zone_id.removeprefix("zone-")
    return AirPlayTarget(
        zone_id=zone_id,
        host="receiver.example.test",
        port=7015,
        device_id=f"device-test-{suffix}",
        player_uuid=f"player-test-{suffix}",
        service_name=f"Receiver {suffix}",
        txt={"deviceid": f"device-test-{suffix}", "model": "Test Receiver"},
        protocol_mode=protocol_mode,
    )


async def test_health_is_public_and_minimal_without_mapping_or_token_leaks() -> None:
    app = create_app(
        targets={"zone-alpha": _target()},
        bearer_token=_TEST_TOKEN,
        allowed_media_hosts={_MEDIA_HOST},
    )

    async with TestServer(app) as server:
        async with TestClient(server) as client:
            response = await client.get("/health")
            payload = await response.json()
            body = await response.text()

    assert response.status == 200
    assert payload == {"status": "ok"}
    assert _TEST_TOKEN not in body
    assert "zone-alpha" not in body
    assert _MEDIA_HOST not in body


async def test_stream_rejects_missing_or_wrong_bearer_token_before_sender() -> None:
    sender = FakeSender()
    app = create_app(
        targets={"zone-alpha": _target()},
        bearer_token=_TEST_TOKEN,
        allowed_media_hosts={_MEDIA_HOST},
        sender_factory=_sender_factory(sender),
    )

    async with TestServer(app) as server:
        async with TestClient(server) as client:
            for header in (None, "Bearer wrong-token", f"bearer {_TEST_TOKEN}"):
                headers = {} if header is None else {"Authorization": header}
                response = await client.post(
                    "/v1/streams",
                    json={"zone_id": "zone-alpha", "media_url": f"https://{_MEDIA_HOST}/clip.wav"},
                    headers=headers,
                )
                assert response.status == 401
                assert await response.json() == {"error": "unauthorized"}

            response = await client.post(
                "/v1/streams",
                json={"zone_id": "zone-alpha", "media_url": f"https://{_MEDIA_HOST}/clip.wav"},
                headers=[
                    ("Authorization", f"Bearer {_TEST_TOKEN}"),
                    ("Authorization", "Bearer wrong-token"),
                ],
            )
            assert response.status == 401
            assert await response.json() == {"error": "unauthorized"}

    assert sender.calls == []


async def test_authorized_stream_schedules_exact_raop_target_and_approved_url() -> None:
    sender = FakeSender()
    target = _target()
    media_url = f"https://{_MEDIA_HOST}/audio.wav?request=test-only"
    app = create_app(
        targets={target.zone_id: target},
        bearer_token=_TEST_TOKEN,
        allowed_media_hosts={_MEDIA_HOST},
        sender_factory=_sender_factory(sender),
    )

    async with TestServer(app) as server:
        async with TestClient(server) as client:
            response = await client.post(
                "/v1/streams",
                json={"zone_id": target.zone_id, "media_url": media_url},
                headers={"Authorization": f"Bearer {_TEST_TOKEN}"},
            )
            payload = await response.json()
            await asyncio.sleep(0)

    assert response.status == 202
    assert payload["status"] == "running"
    assert isinstance(payload["job_id"], str)
    assert payload["job_id"]
    assert target.zone_id not in payload["job_id"]
    assert media_url not in payload["job_id"]
    assert sender.calls == [(target, media_url)]


async def test_stream_rejects_unsafe_or_unapproved_media_urls_before_sender() -> None:
    sender = FakeSender()
    app = create_app(
        targets={"zone-alpha": _target()},
        bearer_token=_TEST_TOKEN,
        allowed_media_hosts={_MEDIA_HOST, "localhost", "127.0.0.1", "::1"},
        sender_factory=_sender_factory(sender),
    )
    invalid_urls = (
        "audio.wav",
        "file:///audio.wav",
        "ftp://media.example.test/audio.wav",
        f"https://user:password@{_MEDIA_HOST}/audio.wav",
        "http://localhost/audio.wav",
        "http://127.0.0.1/audio.wav",
        "http://[::1]/audio.wav",
        "http://[::ffff:127.0.0.1]/audio.wav",
        "http://127.0.0.1./audio.wav",
        f"https://{_MEDIA_HOST}:not-a-port/audio.wav",
        f"https://{_MEDIA_HOST}:99999/audio.wav",
        "https://other.example.test/audio.wav",
    )

    async with TestServer(app) as server:
        async with TestClient(server) as client:
            for media_url in invalid_urls:
                response = await client.post(
                    "/v1/streams",
                    json={"zone_id": "zone-alpha", "media_url": media_url},
                    headers={"Authorization": f"Bearer {_TEST_TOKEN}"},
                )
                assert response.status == 400
                assert await response.json() == {"error": "invalid request"}

    assert sender.calls == []


async def test_stream_requires_exact_json_keys_and_rejects_duplicate_keys() -> None:
    sender = FakeSender()
    app = create_app(
        targets={"zone-alpha": _target()},
        bearer_token=_TEST_TOKEN,
        allowed_media_hosts={_MEDIA_HOST},
        sender_factory=_sender_factory(sender),
    )
    headers = {"Authorization": f"Bearer {_TEST_TOKEN}"}

    async with TestServer(app) as server:
        async with TestClient(server) as client:
            for payload in (
                {"zone_id": "zone-alpha"},
                {"zone_id": "zone-alpha", "media_url": f"https://{_MEDIA_HOST}/a", "extra": 1},
                ["zone-alpha", f"https://{_MEDIA_HOST}/a"],
            ):
                response = await client.post("/v1/streams", json=payload, headers=headers)
                assert response.status == 400
                assert await response.json() == {"error": "invalid request"}

            response = await client.post(
                "/v1/streams",
                data=(
                    '{"zone_id":"zone-alpha","zone_id":"zone-alpha",'
                    f'"media_url":"https://{_MEDIA_HOST}/a"}}'
                ),
                headers={**headers, "Content-Type": "application/json"},
            )
            assert response.status == 400
            assert await response.json() == {"error": "invalid request"}

    assert sender.calls == []


async def test_stream_resolves_only_exact_zone_id_and_rejects_airplay2() -> None:
    sender = FakeSender()
    targets = {
        "zone-alpha": _target(),
        "zone-beta": _target(zone_id="zone-beta"),
    }
    app = create_app(
        targets=targets,
        bearer_token=_TEST_TOKEN,
        allowed_media_hosts={_MEDIA_HOST},
        sender_factory=_sender_factory(sender),
    )
    headers = {"Authorization": f"Bearer {_TEST_TOKEN}"}
    media_url = f"https://{_MEDIA_HOST}/audio.wav"

    async with TestServer(app) as server:
        async with TestClient(server) as client:
            for zone_id in ("Receiver Alpha", "receiver.example.test", "device-test-alpha"):
                response = await client.post(
                    "/v1/streams",
                    json={"zone_id": zone_id, "media_url": media_url},
                    headers=headers,
                )
                assert response.status == 400

            ap2_app = create_app(
                targets={"zone-alpha": _target(protocol_mode="airplay2")},
                bearer_token=_TEST_TOKEN,
                allowed_media_hosts={_MEDIA_HOST},
                sender_factory=_sender_factory(sender),
            )
            async with TestServer(ap2_app) as ap2_server:
                async with TestClient(ap2_server) as ap2_client:
                    response = await ap2_client.post(
                        "/v1/streams",
                        json={"zone_id": "zone-alpha", "media_url": media_url},
                        headers=headers,
                    )
                    assert response.status == 400

    assert sender.calls == []


async def test_job_status_is_running_then_succeeded_with_minimal_payload() -> None:
    sender = BlockingSender()
    app = create_app(
        targets={"zone-alpha": _target()},
        bearer_token=_TEST_TOKEN,
        allowed_media_hosts={_MEDIA_HOST},
        sender_factory=_sender_factory(sender),
    )
    headers = {"Authorization": f"Bearer {_TEST_TOKEN}"}
    media_url = f"https://{_MEDIA_HOST}/audio.wav"

    async with TestServer(app) as server:
        async with TestClient(server) as client:
            response = await client.post(
                "/v1/streams",
                json={"zone_id": "zone-alpha", "media_url": media_url},
                headers=headers,
            )
            created = await response.json()
            await sender.started.wait()

            running_response = await client.get(
                f"/v1/jobs/{created['job_id']}", headers=headers
            )
            running = await running_response.json()
            assert running_response.status == 200
            assert running == {"job_id": created["job_id"], "status": "running"}

            sender.release.set()
            await sender.exited.wait()
            await asyncio.sleep(0)

            succeeded_response = await client.get(
                f"/v1/jobs/{created['job_id']}", headers=headers
            )
            succeeded = await succeeded_response.json()

    assert response.status == 202
    assert created["status"] == "running"
    assert succeeded_response.status == 200
    assert succeeded == {"job_id": created["job_id"], "status": "succeeded"}
    assert set(succeeded) == {"job_id", "status"}
    assert media_url not in str(succeeded)
    assert "Receiver" not in str(succeeded)


async def test_delete_cancels_only_the_selected_running_job() -> None:
    first_sender = BlockingSender()
    second_sender = BlockingSender()
    senders = [first_sender, second_sender]

    def factory() -> BlockingSender:
        return senders.pop(0)

    app = create_app(
        targets={"zone-alpha": _target()},
        bearer_token=_TEST_TOKEN,
        allowed_media_hosts={_MEDIA_HOST},
        sender_factory=factory,
    )
    headers = {"Authorization": f"Bearer {_TEST_TOKEN}"}
    body = {"zone_id": "zone-alpha", "media_url": f"https://{_MEDIA_HOST}/a"}

    async with TestServer(app) as server:
        async with TestClient(server) as client:
            first = await client.post("/v1/streams", json=body, headers=headers)
            first_job = await first.json()
            await first_sender.started.wait()
            second = await client.post("/v1/streams", json=body, headers=headers)
            second_job = await second.json()
            await second_sender.started.wait()

            deleted = await client.delete(
                f"/v1/jobs/{first_job['job_id']}", headers=headers
            )
            deleted_payload = await deleted.json()
            second_state = await client.get(
                f"/v1/jobs/{second_job['job_id']}", headers=headers
            )
            second_payload = await second_state.json()

            second_sender.release.set()
            await second_sender.exited.wait()

    assert deleted.status == 200
    assert deleted_payload == {"job_id": first_job["job_id"], "status": "cancelled"}
    assert first_sender.cancelled is True
    assert first_sender.exited.is_set()
    assert second_state.status == 200
    assert second_payload == {"job_id": second_job["job_id"], "status": "running"}
    assert second_sender.cancelled is False


async def test_shutdown_cancels_and_joins_active_jobs() -> None:
    sender = BlockingSender()
    app = create_app(
        targets={"zone-alpha": _target()},
        bearer_token=_TEST_TOKEN,
        allowed_media_hosts={_MEDIA_HOST},
        sender_factory=_sender_factory(sender),
    )
    headers = {"Authorization": f"Bearer {_TEST_TOKEN}"}

    async with TestServer(app) as server:
        async with TestClient(server) as client:
            response = await client.post(
                "/v1/streams",
                json={"zone_id": "zone-alpha", "media_url": f"https://{_MEDIA_HOST}/a"},
                headers=headers,
            )
            created = await response.json()
            await sender.started.wait()
            await app.cleanup()

    assert sender.cancelled is True
    assert sender.exited.is_set()
    assert response.status == 202
    assert created["status"] == "running"


async def test_empty_media_allowlist_rejects_every_media_url() -> None:
    sender = FakeSender()
    app = create_app(
        targets={"zone-alpha": _target()},
        bearer_token=_TEST_TOKEN,
        allowed_media_hosts=set(),
        sender_factory=_sender_factory(sender),
    )

    async with TestServer(app) as server:
        async with TestClient(server) as client:
            response = await client.post(
                "/v1/streams",
                json={"zone_id": "zone-alpha", "media_url": f"https://{_MEDIA_HOST}/a"},
                headers={"Authorization": f"Bearer {_TEST_TOKEN}"},
            )

    assert response.status == 400
    assert sender.calls == []


@pytest.mark.parametrize("bad_token", ("", "   ", None))
def test_factory_requires_a_nonempty_bearer_token(bad_token: object) -> None:
    with pytest.raises(ValueError, match="bearer_token"):
        create_app(
            targets={"zone-alpha": _target()},
            bearer_token=bad_token,  # type: ignore[arg-type]
            allowed_media_hosts={_MEDIA_HOST},
        )


async def test_failed_sender_exposes_only_failed_job_state() -> None:
    sender = FailingSender()
    media_url = f"https://{_MEDIA_HOST}/private.wav?secret=test-only"
    app = create_app(
        targets={"zone-alpha": _target()},
        bearer_token=_TEST_TOKEN,
        allowed_media_hosts={_MEDIA_HOST},
        sender_factory=_sender_factory(sender),
    )
    headers = {"Authorization": f"Bearer {_TEST_TOKEN}"}

    async with TestServer(app) as server:
        async with TestClient(server) as client:
            created_response = await client.post(
                "/v1/streams",
                json={"zone_id": "zone-alpha", "media_url": media_url},
                headers=headers,
            )
            created = await created_response.json()
            await sender.finished.wait()
            await asyncio.sleep(0)
            state_response = await client.get(
                f"/v1/jobs/{created['job_id']}", headers=headers
            )
            state = await state_response.json()
            state_body = await state_response.text()

    assert state_response.status == 200
    assert state == {"job_id": created["job_id"], "status": "failed"}
    assert "secret receiver" not in state_body
    assert media_url not in state_body
    assert "receiver.example.test" not in state_body


async def test_job_routes_require_auth_and_unknown_ids_are_not_revealing() -> None:
    app = create_app(
        targets={"zone-alpha": _target()},
        bearer_token=_TEST_TOKEN,
        allowed_media_hosts={_MEDIA_HOST},
    )

    async with TestServer(app) as server:
        async with TestClient(server) as client:
            for method in ("get", "delete"):
                response = await getattr(client, method)("/v1/jobs/unknown", headers={})
                assert response.status == 401
                assert await response.json() == {"error": "unauthorized"}

            response = await client.get(
                "/v1/jobs/unknown", headers={"Authorization": f"Bearer {_TEST_TOKEN}"}
            )
            assert response.status == 404
            assert await response.json() == {"error": "not found"}

            response = await client.delete(
                "/v1/jobs/unknown", headers={"Authorization": f"Bearer {_TEST_TOKEN}"}
            )
            assert response.status == 404
            assert await response.json() == {"error": "not found"}


def test_cli_defaults_to_loopback_and_has_no_token_argument() -> None:
    args = build_parser().parse_args(
        [
            "--targets-file",
            "targets.json",
            "--allowed-media-host",
            _MEDIA_HOST,
            "--port",
            "8765",
        ]
    )

    assert args.host == "127.0.0.1"
    assert args.port == 8765
    assert args.allowed_media_hosts == [_MEDIA_HOST]
    assert args.token_env_var == TOKEN_ENV_VAR
    assert not hasattr(args, "bearer_token")


def test_cli_reads_bearer_token_only_from_environment_without_launching_listener(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target_file = tmp_path / "targets.json"
    target_file.write_text(json.dumps(dump_airplay_targets([_target()])), encoding="utf-8")
    monkeypatch.setenv(TOKEN_ENV_VAR, _TEST_TOKEN)
    captured: dict[str, object] = {}

    def fake_run_app(app: object, **kwargs: object) -> None:
        captured["app"] = app
        captured.update(kwargs)

    monkeypatch.setattr(server_module.web, "run_app", fake_run_app)

    main(
        [
            "--targets-file",
            str(target_file),
            "--allowed-media-host",
            _MEDIA_HOST,
            "--port",
            "9876",
        ]
    )

    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 9876
    assert captured["access_log"] is None
