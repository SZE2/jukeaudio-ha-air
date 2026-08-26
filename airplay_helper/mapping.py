"""Strict, in-memory handling of explicit Juke-zone RAOP mappings."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any


_REQUIRED_FIELDS = frozenset(
    {
        "zone_id",
        "host",
        "port",
        "device_id",
        "player_uuid",
        "service_name",
        "txt",
        "protocol_mode",
    }
)
_PROTOCOL_MODES = frozenset({"airplay2", "raop_fallback"})


class AirPlayMappingError(ValueError):
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
    """Load explicit AirPlay target records keyed by Juke zone ID.

    This intentionally mirrors the HACS component's mapping contract without
    importing that component or performing discovery, name matching, or I/O.
    """
    if not isinstance(mapping, Mapping):
        raise AirPlayMappingError("AirPlay mapping must be a mapping")

    targets: list[AirPlayTarget] = []
    for zone_id, record in mapping.items():
        if not isinstance(zone_id, str) or not zone_id.strip():
            raise AirPlayMappingError("AirPlay mapping keys must be non-empty zone_id values")
        if not isinstance(record, Mapping) or record.get("zone_id") != zone_id:
            raise AirPlayMappingError("AirPlay target zone_id must match its mapping key")
        if set(record) != _REQUIRED_FIELDS:
            raise AirPlayMappingError("AirPlay target record has an invalid shape")
        try:
            targets.append(AirPlayTarget(**record))
        except TypeError as err:
            raise AirPlayMappingError("AirPlay target record has an invalid shape") from err

    return _validate_target_collection(targets)


def dump_airplay_targets(
    targets: Iterable[AirPlayTarget],
) -> dict[str, dict[str, object]]:
    """Serialize explicit targets to a JSON-compatible config mapping."""
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


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AirPlayMappingError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_targets_json(payload: str | bytes | bytearray) -> tuple[AirPlayTarget, ...]:
    """Parse and validate a JSON object containing explicit target mappings."""
    if not isinstance(payload, (str, bytes, bytearray)):
        raise AirPlayMappingError("AirPlay targets JSON must be text or bytes")
    try:
        decoded = json.loads(payload, object_pairs_hook=_reject_duplicate_json_keys)
    except AirPlayMappingError:
        raise
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as err:
        raise AirPlayMappingError("AirPlay targets must be valid JSON") from err
    if not isinstance(decoded, Mapping):
        raise AirPlayMappingError("AirPlay targets JSON must contain a JSON object")
    return load_airplay_targets(decoded)


def load_targets_file(path: str | Path) -> tuple[AirPlayTarget, ...]:
    """Read one explicit JSON mapping file without any network access."""
    try:
        with Path(path).open("r", encoding="utf-8") as source:
            return load_targets_json(source.read())
    except OSError as err:
        raise AirPlayMappingError("Unable to read AirPlay targets file") from err


def resolve_raop_target(
    targets: Iterable[AirPlayTarget],
    zone_id: str,
) -> AirPlayTarget:
    """Resolve exactly one mapped zone and require the legacy RAOP mode."""
    for target in _validate_target_collection(targets):
        if target.zone_id == zone_id:
            if target.protocol_mode != "raop_fallback":
                raise AirPlayMappingError(
                    "AirPlay target protocol_mode must be raop_fallback for this helper"
                )
            return target
    raise AirPlayMappingError(f"Unknown zone_id: {zone_id}")
