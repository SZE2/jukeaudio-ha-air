"""Deterministic, user-supplied Juke-zone to AirPlay target mappings.

This module performs no discovery or network I/O.  Its serialized mapping is
JSON-compatible and can be stored explicitly by a future config-entry options
flow without changing the normal Juke connection data.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from homeassistant.exceptions import HomeAssistantError


_PROTOCOL_MODES = frozenset({"airplay2", "raop_fallback"})


class AirPlayMappingError(HomeAssistantError):
    """Raised when an explicit AirPlay target mapping is invalid."""


@dataclass(frozen=True)
class AirPlayTarget:
    """One explicitly approved Juke-zone to AirPlay receiver mapping."""

    zone_id: str
    host: str
    port: int
    device_id: str
    player_uuid: str
    service_name: str
    txt: Mapping[str, str]
    protocol_mode: str

    def __post_init__(self) -> None:
        for field_name in (
            "zone_id",
            "host",
            "device_id",
            "player_uuid",
            "service_name",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise AirPlayMappingError(f"AirPlay target {field_name} must be non-empty")
        if (
            isinstance(self.port, bool)
            or not isinstance(self.port, int)
            or not 1 <= self.port <= 65535
        ):
            raise AirPlayMappingError("AirPlay target port must be between 1 and 65535")
        if not isinstance(self.protocol_mode, str) or self.protocol_mode not in _PROTOCOL_MODES:
            raise AirPlayMappingError("AirPlay target protocol_mode is not recognized")
        if not isinstance(self.txt, Mapping):
            raise AirPlayMappingError("AirPlay target txt must be a mapping")
        frozen_txt: dict[str, str] = {}
        for key, value in self.txt.items():
            if not isinstance(key, str) or not key.strip() or not isinstance(value, str):
                raise AirPlayMappingError("AirPlay target txt must contain string keys and values")
            frozen_txt[key] = value
        object.__setattr__(self, "txt", MappingProxyType(dict(sorted(frozen_txt.items()))))


def _validate_target_collection(
    targets: Iterable[AirPlayTarget],
) -> tuple[AirPlayTarget, ...]:
    """Validate target instances and return them in canonical zone order."""
    try:
        materialized = tuple(targets)
    except TypeError as err:
        raise AirPlayMappingError("AirPlay targets must be iterable") from err
    if not all(isinstance(target, AirPlayTarget) for target in materialized):
        raise AirPlayMappingError("AirPlay targets must be AirPlayTarget instances")

    seen_zones: set[str] = set()
    seen_identities: set[tuple[str, str, int]] = set()
    for target in materialized:
        if target.zone_id in seen_zones:
            raise AirPlayMappingError("AirPlay zone_id must be unique")
        seen_zones.add(target.zone_id)
        identity = (target.device_id, target.player_uuid, target.port)
        if identity in seen_identities:
            raise AirPlayMappingError("AirPlay receiver identity must be unique")
        seen_identities.add(identity)

    return tuple(sorted(materialized, key=lambda target: target.zone_id))


def load_airplay_targets(
    mapping: Mapping[str, Mapping[str, Any]],
) -> tuple[AirPlayTarget, ...]:
    """Load explicit AirPlay target records keyed by Juke zone ID."""
    if not isinstance(mapping, Mapping):
        raise AirPlayMappingError("AirPlay mapping must be a mapping")

    targets: list[AirPlayTarget] = []
    for zone_id, record in mapping.items():
        if not isinstance(zone_id, str) or not zone_id.strip():
            raise AirPlayMappingError("AirPlay mapping keys must be non-empty zone_id values")
        if not isinstance(record, Mapping) or record.get("zone_id") != zone_id:
            raise AirPlayMappingError("AirPlay target zone_id must match its mapping key")
        try:
            targets.append(AirPlayTarget(**record))
        except TypeError as err:
            raise AirPlayMappingError("AirPlay target record has an invalid shape") from err

    return _validate_target_collection(targets)


def dump_airplay_targets(
    targets: Iterable[AirPlayTarget],
) -> dict[str, dict[str, object]]:
    """Serialize explicit targets to a JSON-compatible config-entry mapping."""
    canonical_targets = _validate_target_collection(targets)
    return {
        target.zone_id: {
            "zone_id": target.zone_id,
            "host": target.host,
            "port": target.port,
            "device_id": target.device_id,
            "player_uuid": target.player_uuid,
            "service_name": target.service_name,
            "txt": dict(sorted(target.txt.items())),
            "protocol_mode": target.protocol_mode,
        }
        for target in canonical_targets
    }
