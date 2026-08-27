"""Tests for the Juke v3 operations not covered by jukeaudio 0.0.11."""

from __future__ import annotations

import pytest


class _FakeResponse:
    status = 200

    def __init__(self, payload=None):
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return None

    async def json(self):
        return self.payload

    async def text(self):
        return "ok"


class _FakeSession:
    def __init__(self, *, headers, response_payload=None):
        self.headers = headers
        self.response_payload = response_payload
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return None

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return _FakeResponse(self.response_payload)


@pytest.mark.asyncio
async def test_set_zone_mute_uses_v3_endpoint_and_boolean_payload(monkeypatch):
    """Setting mute uses the dedicated endpoint rather than changing volume."""
    from custom_components.jukeaudio_ha_air import juke_client

    sessions = []

    def make_session(*, headers):
        session = _FakeSession(headers=headers)
        sessions.append(session)
        return session

    monkeypatch.setattr(juke_client.aiohttp, "ClientSession", make_session)

    client = juke_client.JukeAudioClientV3()
    result = await client.set_zone_mute(
        "juke.local", "alice", "secret", "zone-1", True
    )

    assert result == "ok"
    session = sessions[0]
    assert session.headers == {"Authorization": "Bearer YWxpY2U6c2VjcmV0"}
    assert session.calls == [
        (
            "PUT",
            "http://juke.local/api/v3/zones/zone-1/mute",
            {"json": {"enable": True}},
        )
    ]


@pytest.mark.asyncio
async def test_set_zone_enabled_uses_v3_endpoint_and_boolean_payload(monkeypatch):
    """Enabling a zone uses the dedicated enable endpoint."""
    from custom_components.jukeaudio_ha_air import juke_client

    sessions = []

    def make_session(*, headers):
        session = _FakeSession(headers=headers)
        sessions.append(session)
        return session

    monkeypatch.setattr(juke_client.aiohttp, "ClientSession", make_session)

    client = juke_client.JukeAudioClientV3()
    result = await client.set_zone_enabled(
        "juke.local", "alice", "secret", "zone-1", False
    )

    assert result == "ok"
    assert sessions[0].calls == [
        (
            "PUT",
            "http://juke.local/api/v3/zones/zone-1/enable",
            {"json": {"enable": False}},
        )
    ]


@pytest.mark.asyncio
async def test_set_zone_inputs_sends_all_input_ids(monkeypatch):
    """Setting zone inputs sends the complete requested input list."""
    from custom_components.jukeaudio_ha_air import juke_client

    sessions = []

    def make_session(*, headers):
        session = _FakeSession(headers=headers)
        sessions.append(session)
        return session

    monkeypatch.setattr(juke_client.aiohttp, "ClientSession", make_session)

    client = juke_client.JukeAudioClientV3()
    result = await client.set_zone_inputs(
        "juke.local", "alice", "secret", "zone-1", ["input-a", "input-b"]
    )

    assert result == "ok"
    assert sessions[0].calls == [
        (
            "PUT",
            "http://juke.local/api/v3/zones/zone-1/input",
            {"json": {"input_ids": ["input-a", "input-b"]}},
        )
    ]


@pytest.mark.asyncio
async def test_add_input_zone_uses_membership_endpoint(monkeypatch):
    """Adding an input to a zone does not replace other zone inputs."""
    from custom_components.jukeaudio_ha_air import juke_client

    sessions = []

    def make_session(*, headers):
        session = _FakeSession(headers=headers)
        sessions.append(session)
        return session

    monkeypatch.setattr(juke_client.aiohttp, "ClientSession", make_session)

    client = juke_client.JukeAudioClientV3()
    result = await client.add_input_zone(
        "juke.local", "alice", "secret", "input-a", "zone-1"
    )

    assert result == "ok"
    assert sessions[0].calls == [
        (
            "PUT",
            "http://juke.local/api/v3/inputs/input-a/zone/add",
            {"json": {"zone_id": "zone-1"}},
        )
    ]


@pytest.mark.asyncio
async def test_remove_input_zone_uses_membership_endpoint(monkeypatch):
    """Removing an input from a zone uses the dedicated remove endpoint."""
    from custom_components.jukeaudio_ha_air import juke_client

    sessions = []

    def make_session(*, headers):
        session = _FakeSession(headers=headers)
        sessions.append(session)
        return session

    monkeypatch.setattr(juke_client.aiohttp, "ClientSession", make_session)

    client = juke_client.JukeAudioClientV3()
    result = await client.remove_input_zone(
        "juke.local", "alice", "secret", "input-a", "zone-1"
    )

    assert result == "ok"
    assert sessions[0].calls == [
        (
            "PUT",
            "http://juke.local/api/v3/inputs/input-a/zone/remove",
            {"json": {"zone_id": "zone-1"}},
        )
    ]


@pytest.mark.asyncio
async def test_get_active_input_reads_v3_json_endpoint(monkeypatch):
    """Reading the active input returns the endpoint JSON response."""
    from custom_components.jukeaudio_ha_air import juke_client

    sessions = []

    def make_session(*, headers):
        session = _FakeSession(
            headers=headers, response_payload={"input_id": "input-a"}
        )
        sessions.append(session)
        return session

    monkeypatch.setattr(juke_client.aiohttp, "ClientSession", make_session)

    client = juke_client.JukeAudioClientV3()
    result = await client.get_active_input(
        "juke.local", "alice", "secret", "zone-1"
    )

    assert result == {"input_id": "input-a"}
    assert sessions[0].calls == [
        (
            "GET",
            "http://juke.local/api/v3/zones/zone-1/input/active",
            {},
        )
    ]


@pytest.mark.asyncio
async def test_set_active_input_uses_active_input_endpoint(monkeypatch):
    """Selecting the active input uses the active-input PUT endpoint."""
    from custom_components.jukeaudio_ha_air import juke_client

    sessions = []

    def make_session(*, headers):
        session = _FakeSession(headers=headers)
        sessions.append(session)
        return session

    monkeypatch.setattr(juke_client.aiohttp, "ClientSession", make_session)

    client = juke_client.JukeAudioClientV3()
    result = await client.set_active_input(
        "juke.local", "alice", "secret", "zone-1", "input-b"
    )

    assert result == "ok"
    assert sessions[0].calls == [
        (
            "PUT",
            "http://juke.local/api/v3/zones/zone-1/input/active",
            {"json": {"input_id": "input-b"}},
        )
    ]


@pytest.mark.asyncio
async def test_get_streaming_inputs_reads_v3_json_endpoint(monkeypatch):
    """Reading streaming inputs returns the endpoint JSON response."""
    from custom_components.jukeaudio_ha_air import juke_client

    sessions = []

    def make_session(*, headers):
        session = _FakeSession(
            headers=headers, response_payload={"input_ids": ["input-a"]}
        )
        sessions.append(session)
        return session

    monkeypatch.setattr(juke_client.aiohttp, "ClientSession", make_session)

    client = juke_client.JukeAudioClientV3()
    result = await client.get_streaming_inputs(
        "juke.local", "alice", "secret", "zone-1"
    )

    assert result == {"input_ids": ["input-a"]}
    assert sessions[0].calls == [
        (
            "GET",
            "http://juke.local/api/v3/zones/zone-1/input/streaming",
            {},
        )
    ]


@pytest.mark.asyncio
async def test_set_zone_based_input_enabled_uses_validated_endpoint(monkeypatch):
    """Native zone-based input enablement uses the typed endpoint."""
    from custom_components.jukeaudio_ha_air import juke_client

    sessions = []

    def make_session(*, headers):
        session = _FakeSession(headers=headers)
        sessions.append(session)
        return session

    monkeypatch.setattr(juke_client.aiohttp, "ClientSession", make_session)

    client = juke_client.JukeAudioClientV3()
    result = await client.set_zone_based_input_enabled(
        "juke.local", "alice", "secret", "zone-1", "spotify", True
    )

    assert result == "ok"
    assert sessions[0].calls == [
        (
            "PUT",
            "http://juke.local/api/v3/zones/zone-1/input/spotify/enable",
            {"json": {"enable": True}},
        )
    ]


@pytest.mark.asyncio
async def test_set_zone_based_input_enabled_rejects_unknown_type_before_http(
    monkeypatch,
):
    """Unsupported native input types are rejected without a network request."""
    from custom_components.jukeaudio_ha_air import juke_client

    sessions = []

    def make_session(*, headers):
        session = _FakeSession(headers=headers)
        sessions.append(session)
        return session

    monkeypatch.setattr(juke_client.aiohttp, "ClientSession", make_session)

    client = juke_client.JukeAudioClientV3()
    with pytest.raises(ValueError, match="Unsupported zone-based input type"):
        await client.set_zone_based_input_enabled(
            "juke.local", "alice", "secret", "zone-1", "bluetooth", True
        )

    assert sessions == []
