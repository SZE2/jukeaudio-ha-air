"""Tests for explicit integrated RAOP target options."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from homeassistant import config_entries

from custom_components.jukeaudio_ha.airplay import dump_airplay_targets, load_airplay_targets
from custom_components.jukeaudio_ha.config_flow import ConfigFlow
from custom_components.jukeaudio_ha.const import CONF_AIRPLAY_TARGETS


def _entry(options=None):
    return SimpleNamespace(
        entry_id="entry-1",
        data={
            "host": "juke.example",
            "username": "Admin",
            "password": "fixture-password",
            "scan_interval": 30,
        },
        options={} if options is None else options,
    )


def _target_mapping_json() -> str:
    return json.dumps(
        {
            "zone-1": {
                "zone_id": "zone-1",
                "host": "receiver.example",
                "port": 7000,
                "device_id": "AA:BB:CC:DD:EE:01",
                "player_uuid": "player-1",
                "service_name": "Living Receiver",
                "txt": {"deviceid": "AA:BB:CC:DD:EE:01"},
                "protocol_mode": "raop_fallback",
            }
        }
    )


@pytest.mark.asyncio
async def test_options_flow_exposes_only_integrated_raop_mapping():
    """The options UI has no helper URL, token, listener, or job fields."""
    flow = ConfigFlow.async_get_options_flow(
        _entry(
            {
                "helper_base_url": "https://old-helper.example",
                "helper_bearer_token": "fixture-token",
                CONF_AIRPLAY_TARGETS: {},
            }
        )
    )

    assert isinstance(flow, config_entries.OptionsFlow)
    result = await flow.async_step_init()

    assert result["type"] == "form"
    fields = {key.schema for key in result["data_schema"].schema}
    assert fields == {CONF_AIRPLAY_TARGETS}


@pytest.mark.asyncio
async def test_options_save_preserves_unrelated_options_and_discards_legacy_values():
    """Saving targets preserves unrelated options but removes old helper values."""
    original_data = {
        "host": "juke.example",
        "username": "Admin",
        "password": "fixture-password",
        "scan_interval": 30,
    }
    entry = _entry(
        {
            "helper_base_url": "https://old-helper.example",
            "helper_bearer_token": "fixture-existing-token",
            CONF_AIRPLAY_TARGETS: {},
            "unrelated": "preserved",
        }
    )
    entry.data = dict(original_data)
    flow = ConfigFlow.async_get_options_flow(entry)

    result = await flow.async_step_init({CONF_AIRPLAY_TARGETS: _target_mapping_json()})

    expected_targets = dump_airplay_targets(
        load_airplay_targets(json.loads(_target_mapping_json()))
    )
    assert result["type"] == "create_entry"
    assert result["data"] == {"unrelated": "preserved", CONF_AIRPLAY_TARGETS: expected_targets}
    assert entry.data == original_data


@pytest.mark.asyncio
async def test_empty_target_mapping_is_valid_for_initial_options_setup():
    """Users may save options before assigning a receiver to any zone."""
    flow = ConfigFlow.async_get_options_flow(_entry())

    result = await flow.async_step_init({CONF_AIRPLAY_TARGETS: "{}"})

    assert result["type"] == "create_entry"
    assert result["data"] == {CONF_AIRPLAY_TARGETS: {}}


@pytest.mark.asyncio
async def test_malformed_target_mapping_is_rejected():
    """Options reject malformed mapping JSON instead of persisting it."""
    flow = ConfigFlow.async_get_options_flow(_entry())

    result = await flow.async_step_init({CONF_AIRPLAY_TARGETS: "not-json"})

    assert result["type"] == "form"
    assert result["errors"] == {CONF_AIRPLAY_TARGETS: "invalid_target_mapping"}


@pytest.mark.asyncio
async def test_duplicate_target_mapping_keys_are_rejected():
    """Options reject ambiguous duplicate zone records."""
    valid_mapping = _target_mapping_json()
    duplicate_mapping = "{" + valid_mapping[1:-1] + "," + valid_mapping[1:-1] + "}"
    flow = ConfigFlow.async_get_options_flow(_entry())

    result = await flow.async_step_init({CONF_AIRPLAY_TARGETS: duplicate_mapping})

    assert result["type"] == "form"
    assert result["errors"] == {CONF_AIRPLAY_TARGETS: "invalid_target_mapping"}
