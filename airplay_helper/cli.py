"""Explicit-file, one-shot CLI for legacy RAOP fallback streaming."""

from __future__ import annotations

import argparse
import asyncio

from .mapping import AirPlayMappingError, load_targets_file, resolve_raop_target
from .sender import RaopSender


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Stream one WAV file to one explicitly mapped legacy RAOP target."
    )
    parser.add_argument("--targets-file", required=True, help="JSON target mapping file")
    parser.add_argument("--zone-id", required=True, help="Exact mapped Juke zone ID")
    parser.add_argument("--wav-file", required=True, help="One local WAV file to stream")
    return parser


async def _run_once(args: argparse.Namespace) -> None:
    targets = load_targets_file(args.targets_file)
    target = resolve_raop_target(targets, args.zone_id)
    await RaopSender().stream_wav(target, args.wav_file)


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        asyncio.run(_run_once(args))
    except AirPlayMappingError as err:
        parser.error(str(err))


__all__ = ["build_parser", "main"]
