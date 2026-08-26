"""Configured HTTP client for the separately managed RAOP helper.

This module deliberately contains no AirPlay sender implementation.  It only
validates explicit config-entry options and submits an already reachable media
URL to the independently managed helper service.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping
from dataclasses import dataclass

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from yarl import URL

from .airplay import AirPlayTarget, load_airplay_targets

CONF_HELPER_BASE_URL = "helper_base_url"
CONF_HELPER_BEARER_TOKEN = "helper_bearer_token"
CONF_AIRPLAY_TARGETS = "airplay_targets"

_STREAMS_PATH = "/v1/streams"


class AirPlayHelperError(HomeAssistantError):
    """Raised for sanitized helper configuration or request failures."""


@dataclass(frozen=True)
class AirPlayHelperConfig:
    """Validated explicit helper configuration."""

    base_url: str
    bearer_token: str
    targets: tuple[AirPlayTarget, ...]

    @property
    def streams_url(self) -> str:
        """Return the helper stream endpoint built from the validated origin."""
        return f"{self.base_url}{_STREAMS_PATH}"

    def target_for_zone(self, zone_id: str) -> AirPlayTarget | None:
        """Return the exact explicitly configured RAOP target for a zone."""
        for target in self.targets:
            if target.zone_id == zone_id and target.protocol_mode == "raop_fallback":
                return target
        return None


def _validate_helper_base_url(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("invalid helper base URL")
    try:
        parsed = URL(value)
        hostname = parsed.host
        _ = parsed.port
    except (TypeError, ValueError, UnicodeError) as err:
        raise ValueError("invalid helper base URL") from err

    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.is_absolute()
        or not hostname
        or parsed.user is not None
        or parsed.password is not None
        or parsed.query_string
        or parsed.fragment
        or "?" in value
        or "#" in value
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("invalid helper base URL")
    return str(parsed.origin())


def validate_helper_base_url(value: object) -> str:
    """Validate and canonicalize an explicit helper HTTP(S) origin."""
    return _validate_helper_base_url(value)


def _parse_legacy_ipv4(address_text: str) -> ipaddress.IPv4Address | None:
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
    normalized = hostname.rstrip(".").casefold()
    if normalized in {"localhost", "localhost.localdomain", "ip6-localhost"}:
        return True

    # Reject alternate textual forms that HTTP clients may treat as IPv4
    # addresses, without resolving arbitrary hostnames.
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
    """Validate an exact, non-loopback HTTP(S) media URL without fetching it."""
    if not isinstance(value, str) or not value or value != value.strip():
        raise AirPlayHelperError("AirPlay helper received an invalid media URL")
    try:
        parsed = URL(value)
        hostname = parsed.host
    except (TypeError, ValueError, UnicodeError):
        raise AirPlayHelperError("AirPlay helper received an invalid media URL") from None

    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.is_absolute()
        or not hostname
        or parsed.user is not None
        or parsed.password is not None
        or _is_loopback_host(hostname)
    ):
        raise AirPlayHelperError("AirPlay helper received an invalid media URL")
    return value


def load_airplay_helper_config(config_entry: object) -> AirPlayHelperConfig | None:
    """Load valid helper settings solely from config-entry options.

    Invalid or incomplete options are intentionally indistinguishable from an
    unconfigured helper to callers that only need to advertise capabilities.
    """
    options = getattr(config_entry, "options", None)
    if not isinstance(options, Mapping):
        return None
    base_url = options.get(CONF_HELPER_BASE_URL)
    bearer_token = options.get(CONF_HELPER_BEARER_TOKEN)
    target_mapping = options.get(CONF_AIRPLAY_TARGETS)
    if not isinstance(bearer_token, str) or not bearer_token.strip():
        return None
    if not isinstance(target_mapping, Mapping):
        return None
    try:
        validated_base_url = validate_helper_base_url(base_url)
        targets = load_airplay_targets(target_mapping)
    except (TypeError, ValueError, AirPlayHelperError, HomeAssistantError):
        return None
    return AirPlayHelperConfig(validated_base_url, bearer_token, targets)


def has_raop_target(config_entry: object, zone_id: str) -> bool:
    """Return whether valid helper options map this exact zone to RAOP."""
    config = load_airplay_helper_config(config_entry)
    return config is not None and config.target_for_zone(zone_id) is not None


class AirPlayHelperClient:
    """Submit direct media URLs to the explicitly configured helper."""

    def __init__(self, hass: object, config_entry: object) -> None:
        self._hass = hass
        self._config_entry = config_entry

    async def async_play_media(self, zone_id: str, media_url: str) -> str:
        """Submit one exact zone/media pair and return the opaque job ID."""
        config = load_airplay_helper_config(self._config_entry)
        if config is None or config.target_for_zone(zone_id) is None:
            raise AirPlayHelperError("AirPlay helper is not configured for this zone")
        exact_media_url = validate_media_url(media_url)
        payload = {"zone_id": zone_id, "media_url": exact_media_url}
        headers = {"Authorization": f"Bearer {config.bearer_token}"}

        try:
            session = async_get_clientsession(self._hass)
            async with session.post(config.streams_url, json=payload, headers=headers) as response:
                if response.status != 202:
                    raise AirPlayHelperError("AirPlay helper rejected the playback request")
                response_payload = await response.json()
        except AirPlayHelperError:
            raise
        except Exception:
            raise AirPlayHelperError("AirPlay helper playback request failed") from None

        if (
            not isinstance(response_payload, Mapping)
            or not isinstance(response_payload.get("job_id"), str)
            or not response_payload["job_id"].strip()
            or response_payload.get("status") != "running"
        ):
            raise AirPlayHelperError("AirPlay helper returned an invalid playback response")
        return response_payload["job_id"]


__all__ = [
    "AirPlayHelperClient",
    "AirPlayHelperConfig",
    "AirPlayHelperError",
    "CONF_AIRPLAY_TARGETS",
    "CONF_HELPER_BASE_URL",
    "CONF_HELPER_BEARER_TOKEN",
    "has_raop_target",
    "load_airplay_helper_config",
    "validate_helper_base_url",
    "validate_media_url",
]
