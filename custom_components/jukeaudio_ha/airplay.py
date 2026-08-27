"""Deterministic, user-supplied Juke-zone to AirPlay target mappings.

This module performs no discovery or network I/O.  Its serialized mapping is
JSON-compatible and can be stored explicitly by a future config-entry options
flow without changing the normal Juke connection data.
"""

from __future__ import annotations

import asyncio
import inspect
import ipaddress
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from importlib import import_module
from types import MappingProxyType, SimpleNamespace
from typing import Any

from homeassistant.exceptions import HomeAssistantError
from yarl import URL


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


class AirPlayPlaybackError(HomeAssistantError):
    """Raised when direct RAOP playback cannot be safely started."""


@dataclass(frozen=True)
class RaopConfig:
    """Validated direct RAOP configuration from one config entry."""

    targets: tuple[AirPlayTarget, ...]

    def target_for_zone(self, zone_id: str) -> AirPlayTarget | None:
        """Return the exact configured RAOP target for a Juke zone."""
        for target in self.targets:
            if target.zone_id == zone_id and target.protocol_mode == "raop_fallback":
                return target
        return None


# These are RAOP service TXT properties. Target identity fields and arbitrary
# mapping metadata are deliberately not forwarded to ManualService.
_RAOP_TXT_PROPERTIES = frozenset(
    {
        "am",
        "at",
        "ch",
        "cn",
        "da",
        "deviceid",
        "et",
        "features",
        "flags",
        "ft",
        "fv",
        "gcgl",
        "gid",
        "igl",
        "md",
        "model",
        "osvers",
        "pi",
        "pk",
        "pw",
        "rhd",
        "rminm",
        "rmodel",
        "rprod",
        "rvers",
        "sf",
        "sn",
        "srcvers",
        "sr",
        "ss",
        "sv",
        "tp",
        "txtvers",
        "vn",
        "vs",
        "vv",
    }
)
_REMOTE_CLOSE_ERRORS = (ConnectionError, EOFError, OSError)
_PYATV_NOT_CONNECTED_TO_REMOTE = "not connected to remote"
_SHAIRPORT_SYNC_MODEL = "Shairport Sync"


def _parse_legacy_ipv4(address_text: str) -> ipaddress.IPv4Address | None:
    """Parse the legacy numeric IPv4 forms accepted by HTTP clients."""
    parts = address_text.split(".")
    if not 1 <= len(parts) <= 4 or any(not part for part in parts):
        return None

    values: list[int] = []
    for part in parts:
        if part[:2].casefold() == "0x":
            digits = part[2:]
            if not digits or any(char not in "0123456789abcdef" for char in digits.casefold()):
                return None
            base = 16
        elif len(part) > 1 and part.startswith("0"):
            if any(char not in "01234567" for char in part):
                return None
            base = 8
        elif all("0" <= char <= "9" for char in part):
            base = 10
        else:
            return None
        values.append(int(part, base))

    limits = {
        1: (0xFFFFFFFF,),
        2: (0xFF, 0xFFFFFF),
        3: (0xFF, 0xFF, 0xFFFF),
        4: (0xFF, 0xFF, 0xFF, 0xFF),
    }[len(values)]
    if any(value > limit for value, limit in zip(values, limits)):
        return None

    if len(values) == 1:
        numeric_address = values[0]
    elif len(values) == 2:
        numeric_address = (values[0] << 24) | values[1]
    elif len(values) == 3:
        numeric_address = (values[0] << 24) | (values[1] << 16) | values[2]
    else:
        numeric_address = (
            (values[0] << 24)
            | (values[1] << 16)
            | (values[2] << 8)
            | values[3]
        )
    return ipaddress.IPv4Address(numeric_address)


def _is_loopback_host(hostname: str) -> bool:
    """Reject loopback names, addresses, and legacy numeric aliases."""
    normalized = hostname.rstrip(".").casefold()
    if normalized in {"localhost", "localhost.localdomain", "ip6-localhost"}:
        return True

    address_text = normalized.split("%", 1)[0]
    try:
        address = ipaddress.ip_address(address_text)
    except ValueError:
        address = _parse_legacy_ipv4(address_text)
    return address is not None and (
        address.is_loopback
        or (
            address.version == 6
            and address.ipv4_mapped is not None
            and address.ipv4_mapped.is_loopback
        )
    )


def validate_media_url(value: object) -> str:
    """Validate an exact non-loopback HTTP(S) media URL without fetching it."""
    if not isinstance(value, str) or not value or value != value.strip():
        raise AirPlayPlaybackError("Direct RAOP playback received an invalid media URL")
    try:
        parsed = URL(value)
        hostname = parsed.host
        _ = parsed.port
    except (TypeError, ValueError, UnicodeError):
        raise AirPlayPlaybackError(
            "Direct RAOP playback received an invalid media URL"
        ) from None

    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.is_absolute()
        or not hostname
        or parsed.user is not None
        or parsed.password is not None
        or _is_loopback_host(hostname)
    ):
        raise AirPlayPlaybackError("Direct RAOP playback received an invalid media URL")
    return value


def load_raop_config(config_entry: object) -> RaopConfig | None:
    """Load only the explicit RAOP mapping from config-entry options."""
    options = getattr(config_entry, "options", None)
    if not isinstance(options, Mapping):
        return None
    target_mapping = options.get("airplay_targets")
    if not isinstance(target_mapping, Mapping):
        return None
    try:
        targets = load_airplay_targets(target_mapping)
    except (TypeError, ValueError, AirPlayMappingError, HomeAssistantError):
        return None
    return RaopConfig(targets)


def has_raop_target(config_entry: object, zone_id: str) -> bool:
    """Return whether this exact zone has an approved RAOP target."""
    config = load_raop_config(config_entry)
    return config is not None and config.target_for_zone(zone_id) is not None


def _load_pyatv() -> Any:
    """Load pyatv lazily only when a direct stream is requested."""
    try:
        pyatv = import_module("pyatv")
        return SimpleNamespace(
            connect=pyatv.connect,
            conf=import_module("pyatv.conf"),
            const=import_module("pyatv.const"),
        )
    except (AttributeError, ImportError) as err:
        raise AirPlayPlaybackError(
            "Direct RAOP playback requires pyatv==0.18.0"
        ) from err


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _normalize_close_tasks(close_result: Any) -> tuple[Any, ...]:
    """Normalize pyatv's iterable of close tasks."""
    try:
        close_tasks = tuple(close_result)
    except TypeError as err:
        raise TypeError(
            "receiver.close() must return an iterable of awaitable tasks"
        ) from err
    if not all(inspect.isawaitable(task) for task in close_tasks):
        raise TypeError(
            "receiver.close() must return an iterable of awaitable tasks"
        )
    return close_tasks


async def _await_close_tasks(receiver: Any) -> tuple[BaseException, ...]:
    """Await all tasks returned by ``AppleTV.close`` and collect errors."""
    close_tasks = _normalize_close_tasks(receiver.close())
    if not close_tasks:
        return ()
    results = await asyncio.gather(*close_tasks, return_exceptions=True)
    return tuple(result for result in results if isinstance(result, BaseException))


def _is_shairport_post_transfer_teardown(
    target: AirPlayTarget,
    error: BaseException,
) -> bool:
    """Recognize only the observed pyatv/Shairport post-transfer teardown."""
    return (
        type(error) is RuntimeError
        and str(error) == _PYATV_NOT_CONNECTED_TO_REMOTE
        and target.txt.get("model") == _SHAIRPORT_SYNC_MODEL
    )


class RaopSender:
    """Send one URL through pyatv's legacy RAOP stream interface."""

    async def stream_url(self, target: AirPlayTarget, media_url: str) -> None:
        """Connect to the explicit target, stream the URL, and close."""
        if target.protocol_mode != "raop_fallback":
            raise AirPlayPlaybackError(
                "Direct RAOP sender requires protocol_mode=raop_fallback"
            )

        exact_media_url = validate_media_url(media_url)
        pyatv = _load_pyatv()
        properties = {
            key: value
            for key, value in target.txt.items()
            if key in _RAOP_TXT_PROPERTIES
        }
        service = pyatv.conf.ManualService(
            f"raop:{target.device_id}:{target.player_uuid}:{target.port}",
            pyatv.const.Protocol.RAOP,
            target.port,
            properties,
        )
        config = pyatv.conf.AppleTV(target.host, target.service_name)
        config.add_service(service)
        receiver = await pyatv.connect(config, asyncio.get_running_loop())

        try:
            await _maybe_await(receiver.stream.stream_file(exact_media_url))
        except BaseException as stream_error:
            if not _is_shairport_post_transfer_teardown(target, stream_error):
                try:
                    await _await_close_tasks(receiver)
                except BaseException:
                    pass
                raise
        close_errors = await _await_close_tasks(receiver)
        for close_error in close_errors:
            if not (
                isinstance(close_error, _REMOTE_CLOSE_ERRORS)
                or (
                    type(close_error) is RuntimeError
                    and str(close_error) == _PYATV_NOT_CONNECTED_TO_REMOTE
                )
            ):
                raise close_error

    async def stream_wav(self, target: AirPlayTarget, wav_source: str) -> None:
        """Compatibility alias for the sender's URL/file source contract."""
        await self.stream_url(target, wav_source)


class DirectRaopClient:
    """Play approved media URLs directly from the component through pyatv."""

    def __init__(
        self,
        config_entry: object,
        *,
        sender_factory: Callable[[], RaopSender] = RaopSender,
    ) -> None:
        self._config_entry = config_entry
        self._sender_factory = sender_factory

    async def async_play_media(self, zone_id: str, media_url: str) -> None:
        """Validate one exact zone/media pair and stream it in-process."""
        config = load_raop_config(self._config_entry)
        target = config.target_for_zone(zone_id) if config is not None else None
        if target is None:
            raise AirPlayPlaybackError(
                "Direct RAOP playback is not configured for this zone"
            )
        exact_media_url = validate_media_url(media_url)
        await self._sender_factory().stream_url(target, exact_media_url)


__all__ = [
    "AirPlayMappingError",
    "AirPlayPlaybackError",
    "AirPlayTarget",
    "DirectRaopClient",
    "RaopConfig",
    "RaopSender",
    "dump_airplay_targets",
    "has_raop_target",
    "load_airplay_targets",
    "load_raop_config",
    "validate_media_url",
]
