"""Pure contract tests for explicit Juke-zone AirPlay target mappings."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from custom_components.jukeaudio_ha_air.airplay import (
    AirPlayMappingError,
    dump_airplay_targets,
    load_airplay_targets,
)


def _record(*, zone_id: str = "zone-a", **overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "zone_id": zone_id,
        "host": "receiver-a.local",
        "port": 7000,
        "device_id": "AA:BB:CC:DD:EE:01",
        "player_uuid": "player-a",
        "service_name": "Living Receiver",
        "txt": {"deviceid": "AA:BB:CC:DD:EE:01"},
        "protocol_mode": "airplay2",
    }
    record.update(overrides)
    return record


def test_mapping_key_must_match_target_zone_id() -> None:
    """A target cannot be stored under a different Juke zone ID."""
    with pytest.raises(AirPlayMappingError, match="zone_id"):
        load_airplay_targets({"zone-a": _record(zone_id="zone-b")})


def test_duplicate_receiver_identity_is_rejected_even_when_names_differ() -> None:
    """Receiver identity, not a friendly service name, determines uniqueness."""
    first = _record(zone_id="zone-a", service_name="Living Receiver")
    second = _record(zone_id="zone-b", service_name="Kitchen Receiver")

    with pytest.raises(AirPlayMappingError, match="identity"):
        load_airplay_targets({"zone-a": first, "zone-b": second})


@pytest.mark.parametrize(
    ("field", "value"),
    [("port", 0), ("port", 65536), ("protocol_mode", "bonjour")],
)
def test_invalid_port_or_protocol_mode_is_rejected(
    field: str, value: object
) -> None:
    """Only network ports and sender modes in the explicit contract are accepted."""
    with pytest.raises(AirPlayMappingError, match=field):
        load_airplay_targets({"zone-a": _record(**{field: value})})


def test_input_service_order_cannot_change_serialized_mapping() -> None:
    """Serialization is canonical regardless of the supplied target order."""
    first = load_airplay_targets(
        {
            "zone-b": _record(
                zone_id="zone-b",
                device_id="AA:BB:CC:DD:EE:02",
                player_uuid="player-b",
                service_name="Kitchen Receiver",
            ),
            "zone-a": _record(zone_id="zone-a"),
        }
    )

    assert dump_airplay_targets(first) == dump_airplay_targets(tuple(reversed(first)))


def test_round_trip_preserves_immutable_target_identity() -> None:
    """Serialization retains all identity fields and target immutability."""
    original = load_airplay_targets({"zone-a": _record()})
    restored = load_airplay_targets(dump_airplay_targets(original))

    assert restored == original
    with pytest.raises(FrozenInstanceError):
        restored[0].host = "other.local"  # type: ignore[misc]
    with pytest.raises(TypeError):
        restored[0].txt["new"] = "value"  # type: ignore[index]


def test_empty_mapping_is_permitted_and_round_trips() -> None:
    """Users may defer all receiver assignments without a placeholder target."""
    assert load_airplay_targets({}) == ()
    assert dump_airplay_targets(()) == {}


@pytest.mark.parametrize("field", ["zone_id", "host", "device_id", "player_uuid", "service_name"])
def test_required_target_identity_fields_must_be_non_empty(field: str) -> None:
    """Every explicit target identity field is required."""
    with pytest.raises(AirPlayMappingError, match=field):
        load_airplay_targets({"zone-a": _record(**{field: ""})})


def test_source_structure_cannot_define_ip_only_or_name_only_targets() -> None:
    """A host or friendly name alone cannot create an AirPlay target."""
    with pytest.raises(AirPlayMappingError):
        load_airplay_targets({"zone-a": {"host": "receiver-a.local"}})
    with pytest.raises(AirPlayMappingError):
        load_airplay_targets({"zone-a": {"service_name": "Living Receiver"}})


def test_serialized_records_have_no_juke_credentials_or_unrecognized_fields() -> None:
    """Config-entry payloads contain only the explicit receiver contract."""
    with pytest.raises(AirPlayMappingError):
        load_airplay_targets({"zone-a": _record(password="not-stored")})

    serialized = dump_airplay_targets(load_airplay_targets({"zone-a": _record()}))
    assert set(serialized["zone-a"]) == {
        "zone_id",
        "host",
        "port",
        "device_id",
        "player_uuid",
        "service_name",
        "txt",
        "protocol_mode",
    }
