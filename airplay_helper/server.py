"""Loopback-friendly HTTP control plane for the isolated RAOP helper."""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import os
import secrets
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from aiohttp import web
from yarl import URL

from .mapping import AirPlayMappingError, AirPlayTarget, load_targets_file
from .sender import RaopSender


_AUTHORIZATION_HEADER = "Authorization"
_HEALTH_PATH = "/health"
_STREAMS_PATH = "/v1/streams"
_JOB_PATH = "/v1/jobs/{job_id}"
_RUNNING = "running"
_SUCCEEDED = "succeeded"
_FAILED = "failed"
_CANCELLED = "cancelled"
_VALID_STATUSES = frozenset({_RUNNING, _SUCCEEDED, _FAILED, _CANCELLED})
TOKEN_ENV_VAR = "AIRPLAY_HELPER_BEARER_TOKEN"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


@dataclass
class _Job:
    job_id: str
    status: str = _RUNNING
    task: asyncio.Task[None] | None = None


@dataclass
class _State:
    targets: dict[str, AirPlayTarget]
    bearer_token: str
    allowed_media_hosts: frozenset[str]
    sender_factory: Callable[[], Any]
    jobs: dict[str, _Job] = field(default_factory=dict)


_STATE_KEY: web.AppKey[_State] = web.AppKey("airplay_helper_state")


async def _health(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


def _error_response(status: int, error: str) -> web.Response:
    return web.json_response({"error": error}, status=status)


def _is_authorized(request: web.Request, bearer_token: str) -> bool:
    values = request.headers.getall(_AUTHORIZATION_HEADER, [])
    return len(values) == 1 and secrets.compare_digest(
        values[0], f"Bearer {bearer_token}"
    )


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _load_request_json(value: str) -> object:
    return json.loads(value, object_pairs_hook=_reject_duplicate_json_keys)


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


def _validate_media_url(media_url: object, allowed_media_hosts: frozenset[str]) -> str:
    if not isinstance(media_url, str) or not media_url:
        raise ValueError("invalid media URL")
    try:
        parsed = URL(media_url)
        hostname = parsed.host
        user = parsed.user
        password = parsed.password
    except (TypeError, ValueError, UnicodeError) as err:
        raise ValueError("invalid media URL") from err

    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.is_absolute()
        or not hostname
        or user is not None
        or password is not None
        or _is_loopback_host(hostname)
        or hostname not in allowed_media_hosts
    ):
        raise ValueError("invalid media URL")
    return media_url


def _snapshot_targets(
    targets: Mapping[str, AirPlayTarget] | Iterable[AirPlayTarget],
) -> dict[str, AirPlayTarget]:
    if isinstance(targets, Mapping):
        materialized: list[AirPlayTarget] = []
        for mapping_zone_id, target in targets.items():
            if not isinstance(mapping_zone_id, str) or not isinstance(target, AirPlayTarget):
                raise ValueError("targets must be explicit AirPlayTarget mappings")
            if mapping_zone_id != target.zone_id:
                raise ValueError("target mapping key must match zone_id")
            materialized.append(target)
    else:
        try:
            materialized = list(targets)
        except TypeError as err:
            raise ValueError("targets must be iterable") from err

    snapshot: dict[str, AirPlayTarget] = {}
    identities: set[tuple[str, str, int]] = set()
    for target in materialized:
        if not isinstance(target, AirPlayTarget):
            raise ValueError("targets must contain AirPlayTarget instances")
        if target.zone_id in snapshot:
            raise ValueError("target zone_id must be unique")
        identity = (target.device_id, target.player_uuid, target.port)
        if identity in identities:
            raise ValueError("target receiver identity must be unique")
        snapshot[target.zone_id] = target
        identities.add(identity)
    return snapshot


def _snapshot_allowed_hosts(allowed_media_hosts: Iterable[str]) -> frozenset[str]:
    if isinstance(allowed_media_hosts, (str, bytes, bytearray)):
        raise ValueError("allowed_media_hosts must be an iterable of hostnames")
    try:
        hosts = frozenset(allowed_media_hosts)
    except TypeError as err:
        raise ValueError("allowed_media_hosts must be an iterable of hostnames") from err
    if not all(isinstance(host, str) and host.strip() == host and host for host in hosts):
        raise ValueError("allowed_media_hosts must contain non-empty hostnames")
    return hosts


def _new_job_id(jobs: Mapping[str, _Job]) -> str:
    job_id = secrets.token_urlsafe(18)
    while job_id in jobs:
        job_id = secrets.token_urlsafe(18)
    return job_id


async def _run_job(
    state: _State,
    job: _Job,
    target: AirPlayTarget,
    media_url: str,
) -> None:
    try:
        sender = state.sender_factory()
        await sender.stream_wav(target, media_url)
    except asyncio.CancelledError:
        job.status = _CANCELLED
    except BaseException:
        job.status = _FAILED
    else:
        job.status = _SUCCEEDED


def _job_payload(job: _Job) -> dict[str, str]:
    return {"job_id": job.job_id, "status": job.status}


async def _create_stream(request: web.Request) -> web.Response:
    state = request.app[_STATE_KEY]
    if not _is_authorized(request, state.bearer_token):
        return _error_response(401, "unauthorized")

    try:
        payload = await request.json(loads=_load_request_json)
        if (
            not isinstance(payload, dict)
            or set(payload) != {"zone_id", "media_url"}
            or not isinstance(payload["zone_id"], str)
        ):
            raise ValueError("invalid request")
        zone_id = payload["zone_id"]
        target = state.targets.get(zone_id)
        if target is None or target.protocol_mode != "raop_fallback":
            raise ValueError("invalid request")
        media_url = _validate_media_url(payload["media_url"], state.allowed_media_hosts)
    except Exception:
        return _error_response(400, "invalid request")

    job = _Job(job_id=_new_job_id(state.jobs))
    state.jobs[job.job_id] = job
    job.task = asyncio.create_task(_run_job(state, job, target, media_url))
    return web.json_response({"job_id": job.job_id, "status": _RUNNING}, status=202)


async def _get_job(request: web.Request) -> web.Response:
    state = request.app[_STATE_KEY]
    if not _is_authorized(request, state.bearer_token):
        return _error_response(401, "unauthorized")
    job = state.jobs.get(request.match_info["job_id"])
    if job is None:
        return _error_response(404, "not found")
    return web.json_response(_job_payload(job))


async def _delete_job(request: web.Request) -> web.Response:
    state = request.app[_STATE_KEY]
    if not _is_authorized(request, state.bearer_token):
        return _error_response(401, "unauthorized")
    job = state.jobs.get(request.match_info["job_id"])
    if job is None:
        return _error_response(404, "not found")
    if job.status == _RUNNING and job.task is not None and not job.task.done():
        job.task.cancel()
        await asyncio.gather(job.task, return_exceptions=True)
        if job.status == _RUNNING:
            job.status = _CANCELLED
    return web.json_response(_job_payload(job))


async def _shutdown(app: web.Application) -> None:
    state = app[_STATE_KEY]
    active_jobs = [
        job
        for job in state.jobs.values()
        if job.status == _RUNNING and job.task is not None and not job.task.done()
    ]
    for job in active_jobs:
        assert job.task is not None
        job.task.cancel()
    if active_jobs:
        await asyncio.gather(
            *(job.task for job in active_jobs if job.task is not None),
            return_exceptions=True,
        )
        for job in active_jobs:
            if job.status == _RUNNING:
                job.status = _CANCELLED


def create_app(
    targets: Mapping[str, AirPlayTarget] | Iterable[AirPlayTarget],
    bearer_token: str,
    allowed_media_hosts: Iterable[str],
    sender_factory: Callable[[], Any] = RaopSender,
) -> web.Application:
    """Build the isolated helper control-plane application."""
    if not isinstance(bearer_token, str) or not bearer_token.strip():
        raise ValueError("bearer_token must be a non-empty string")
    if not callable(sender_factory):
        raise ValueError("sender_factory must be callable")

    state = _State(
        targets=_snapshot_targets(targets),
        bearer_token=bearer_token,
        allowed_media_hosts=_snapshot_allowed_hosts(allowed_media_hosts),
        sender_factory=sender_factory,
    )
    app = web.Application()
    app[_STATE_KEY] = state
    app.router.add_get(_HEALTH_PATH, _health)
    app.router.add_post(_STREAMS_PATH, _create_stream)
    app.router.add_get(_JOB_PATH, _get_job)
    app.router.add_delete(_JOB_PATH, _delete_job)
    app.on_cleanup.append(_shutdown)
    return app


def build_parser() -> argparse.ArgumentParser:
    """Build the HTTP control-plane CLI parser without reading secrets."""
    parser = argparse.ArgumentParser(
        description="Run the isolated RAOP helper HTTP control plane."
    )
    parser.add_argument("--targets-file", required=True, help="JSON target mapping file")
    parser.add_argument(
        "--token-env-var",
        "--token-env",
        dest="token_env_var",
        default=TOKEN_ENV_VAR,
        help="Environment variable containing the bearer token",
    )
    parser.add_argument(
        "--allowed-media-host",
        dest="allowed_media_hosts",
        action="append",
        required=True,
        help="Exact hostname approved for HTTP media URLs; repeat for multiple hosts",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--host", default=DEFAULT_HOST)
    return parser


def main(argv: list[str] | None = None) -> None:
    """Load local configuration and run the control plane."""
    parser = build_parser()
    args = parser.parse_args(argv)
    bearer_token = os.environ.get(args.token_env_var)
    if not bearer_token:
        parser.error(f"Bearer token environment variable {args.token_env_var!r} is not set")
    try:
        targets = load_targets_file(args.targets_file)
        app = create_app(
            targets=targets,
            bearer_token=bearer_token,
            allowed_media_hosts=args.allowed_media_hosts,
        )
    except (AirPlayMappingError, ValueError) as err:
        parser.error(str(err))
    web.run_app(app, host=args.host, port=args.port, access_log=None)


__all__ = ["DEFAULT_HOST", "DEFAULT_PORT", "TOKEN_ENV_VAR", "build_parser", "create_app", "main"]


if __name__ == "__main__":
    main()
