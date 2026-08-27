"""Additional Juke v3 operations missing from jukeaudio 0.0.11."""

from __future__ import annotations

import aiohttp

from jukeaudio.exceptions import AuthenticationException, UnexpectedException
from jukeaudio.jukeaudio_v3 import (
    JukeAudioClientV3 as _UpstreamJukeAudioClientV3,
    api_version,
    create_auth_header,
)


class JukeAudioClientV3(_UpstreamJukeAudioClientV3):
    """Upstream Juke client with the remaining safe v3 operations."""

    async def _request(
        self,
        method: str,
        ip_address: str,
        username: str,
        password: str,
        path: str,
        *,
        payload: dict | None = None,
        response_is_json: bool = False,
    ):
        """Perform one authenticated v3 request using upstream error semantics."""
        headers = {"Authorization": f"Bearer {create_auth_header(username, password)}"}
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.request(
                    method,
                    f"http://{ip_address}/api/{api_version}{path}",
                    **({"json": payload} if payload is not None else {}),
                ) as response:
                    if response.status != 200:
                        if response.status in (401, 403):
                            raise AuthenticationException
                        raise UnexpectedException(response.status)
                    if response_is_json:
                        return await response.json()
                    return await response.text()
        except aiohttp.ClientError as exc:
            raise UnexpectedException from exc

    async def set_zone_mute(
        self,
        ip_address: str,
        username: str,
        password: str,
        zone_id: str,
        muted: bool,
    ):
        """Mute or unmute a zone without changing its volume."""
        return await self._request(
            "PUT",
            ip_address,
            username,
            password,
            f"/zones/{zone_id}/mute",
            payload={"enable": muted},
        )

    async def set_zone_enabled(
        self,
        ip_address: str,
        username: str,
        password: str,
        zone_id: str,
        enabled: bool,
    ):
        """Enable or disable a zone."""
        return await self._request(
            "PUT",
            ip_address,
            username,
            password,
            f"/zones/{zone_id}/enable",
            payload={"enable": enabled},
        )

    async def set_zone_inputs(
        self,
        ip_address: str,
        username: str,
        password: str,
        zone_id: str,
        input_ids: list[str],
    ):
        """Replace the inputs assigned to a zone."""
        return await self._request(
            "PUT",
            ip_address,
            username,
            password,
            f"/zones/{zone_id}/input",
            payload={"input_ids": input_ids},
        )

    async def add_input_zone(
        self,
        ip_address: str,
        username: str,
        password: str,
        input_id: str,
        zone_id: str,
    ):
        """Add one zone to an input without replacing existing memberships."""
        return await self._request(
            "PUT",
            ip_address,
            username,
            password,
            f"/inputs/{input_id}/zone/add",
            payload={"zone_id": zone_id},
        )

    async def remove_input_zone(
        self,
        ip_address: str,
        username: str,
        password: str,
        input_id: str,
        zone_id: str,
    ):
        """Remove one zone from an input without changing other memberships."""
        return await self._request(
            "PUT",
            ip_address,
            username,
            password,
            f"/inputs/{input_id}/zone/remove",
            payload={"zone_id": zone_id},
        )

    async def get_active_input(
        self,
        ip_address: str,
        username: str,
        password: str,
        zone_id: str,
    ):
        """Return the active input for a zone."""
        return await self._request(
            "GET",
            ip_address,
            username,
            password,
            f"/zones/{zone_id}/input/active",
            response_is_json=True,
        )

    async def set_active_input(
        self,
        ip_address: str,
        username: str,
        password: str,
        zone_id: str,
        input_id: str,
    ):
        """Select the active input for a zone."""
        return await self._request(
            "PUT",
            ip_address,
            username,
            password,
            f"/zones/{zone_id}/input/active",
            payload={"input_id": input_id},
        )

    async def get_streaming_inputs(
        self,
        ip_address: str,
        username: str,
        password: str,
        zone_id: str,
    ):
        """Return streaming inputs associated with a zone."""
        return await self._request(
            "GET",
            ip_address,
            username,
            password,
            f"/zones/{zone_id}/input/streaming",
            response_is_json=True,
        )

    async def set_zone_based_input_enabled(
        self,
        ip_address: str,
        username: str,
        password: str,
        zone_id: str,
        input_type: str,
        enabled: bool,
    ):
        """Enable or disable one supported native zone-based input type."""
        if input_type not in {"airplay2", "spotify", "all"}:
            raise ValueError(f"Unsupported zone-based input type: {input_type}")
        return await self._request(
            "PUT",
            ip_address,
            username,
            password,
            f"/zones/{zone_id}/input/{input_type}/enable",
            payload={"enable": enabled},
        )
