"""Lazy pyatv 0.18 RAOP adapter for one-shot WAV streaming."""

from __future__ import annotations

import asyncio
import inspect
from importlib import import_module
from types import SimpleNamespace
from typing import Any

from .mapping import AirPlayTarget


# These are RAOP service TXT properties.  Target identity fields and arbitrary
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


def _load_pyatv() -> Any:
    """Load pyatv modules only when a stream is requested."""
    try:
        pyatv = import_module("pyatv")
        return SimpleNamespace(
            connect=pyatv.connect,
            conf=import_module("pyatv.conf"),
            const=import_module("pyatv.const"),
        )
    except (AttributeError, ImportError) as err:
        raise RuntimeError(
            "The isolated RAOP helper requires pyatv==0.18.0"
        ) from err


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


class RaopSender:
    """Send one WAV source through pyatv's legacy RAOP audio interface."""

    async def stream_wav(self, target: AirPlayTarget, wav_source: str) -> None:
        """Connect to the explicit target, stream exactly ``wav_source``, and close."""
        if target.protocol_mode != "raop_fallback":
            raise ValueError("RaopSender requires target protocol_mode=raop_fallback")

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
            await _maybe_await(receiver.audio.stream_file(wav_source))
        except BaseException:
            # Preserve every setup/connection/stream failure.  Cleanup is best
            # effort here so a second socket error cannot mask the real failure.
            try:
                await _maybe_await(receiver.close())
            except BaseException:
                pass
            raise

        try:
            await _maybe_await(receiver.close())
        except _REMOTE_CLOSE_ERRORS:
            # Some RAOP receivers close their control socket immediately after
            # accepting the completed transfer.  Only this post-stream close is
            # tolerated; setup and stream failures remain failures above.
            pass


__all__ = ["RaopSender"]
