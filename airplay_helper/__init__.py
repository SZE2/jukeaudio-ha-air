"""Isolated legacy RAOP fallback sender for explicitly mapped targets."""

from .mapping import (
    AirPlayMappingError,
    AirPlayTarget,
    dump_airplay_targets,
    load_airplay_targets,
    load_targets_file,
    load_targets_json,
    resolve_raop_target,
)
from .sender import RaopSender

__all__ = [
    "AirPlayMappingError",
    "AirPlayTarget",
    "RaopSender",
    "dump_airplay_targets",
    "load_airplay_targets",
    "load_targets_file",
    "load_targets_json",
    "resolve_raop_target",
]
