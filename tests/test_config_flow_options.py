"""Tests for explicit RAOP helper options configuration."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from homeassistant import config_entries

from custom_components.jukeaudio_ha.airplay import dump_airplay_targets, load_airplay_targets
from custom_components.jukeaudio_ha.airplay_helper import (
    CONF_AIRPLAY_TARGETS,
    CONF_HELPER_BASE_URL,
    CONF_HELPER_BEARER_TOKEN,
)
from custom_components.jukeaudio_ha.config_flow import ConfigFlow


def _entry(options=None):
    return SimpleNamespace(
        entry_id="entry-1",
        data={"host": "juke.example", "username": "Admin", "password": "fixture-password", "scan_interval": 30},
        options=options or {},
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
async def test_options_flow_form_keeps_existing_bearer_token_blank():
    """An options form never renders an already configured bearer token."""
    flow = ConfigFlow.async_get_options_flow(
        _entry(
            {
                CONF_HELPER_BASE_URL: "https://helper.example",
                CONF_HELPER_BEARER_TOKEN: "fixture-bearer-token",
                CONF_AIRPLAY_TARGETS: {},
            }
        )
    )

    assert isinstance(flow, config_entries.OptionsFlow)
    result = await flow.async_step_init()

    assert result["type"] == "form"
    schema = result["data_schema"]
    token_field = next(
        key for key in schema.schema if getattr(key, "schema", None) == CONF_HELPER_BEARER_TOKEN
    )
    assert token_field.default() == ""


@pytest.mark.asyncio
async def test_blank_token_preserves_existing_options_and_data():
    """Saving helper options with a blank token preserves the old token."""
    original_data = {
        "host": "juke.example",
        "username": "Admin",
        "password": "fixture-password",
        "scan_interval": 30,
    }
    entry = _entry(
        {
            CONF_HELPER_BASE_URL: "https://old-helper.example",
            CONF_HELPER_BEARER_TOKEN: "fixture-existing-token",
            CONF_AIRPLAY_TARGETS: {},
            "unrelated": "preserved",
        }
    )
    entry.data = dict(original_data)
    flow = ConfigFlow.async_get_options_flow(entry)

    result = await flow.async_step_init(
        {
            CONF_HELPER_BASE_URL: "https://helper.example/",
            CONF_AIRPLAY_TARGETS: _target_mapping_json(),
            CONF_HELPER_BEARER_TOKEN: "",
        }
    )

    assert result["type"] == "create_entry"
    assert result["data"][CONF_HELPER_BASE_URL] == "https://helper.example"
    assert result["data"][CONF_HELPER_BEARER_TOKEN] == "fixture-existing-token"
    assert result["data"][CONF_AIRPLAY_TARGETS] == dump_airplay_targets(
        load_airplay_targets(json.loads(_target_mapping_json()))
    )
    assert result["data"]["unrelated"] == "preserved"
    assert entry.data == original_data


@pytest.mark.asyncio
async def test_first_options_setup_requires_bearer_token():
    """The first helper setup cannot be saved without a token."""
    flow = ConfigFlow.async_get_options_flow(_entry())

    result = await flow.async_step_init(
        {
            CONF_HELPER_BASE_URL: "https://helper.example",
            CONF_AIRPLAY_TARGETS: "{}",
            CONF_HELPER_BEARER_TOKEN: "",
        }
    )

    assert result["type"] == "form"
    assert result["errors"] == {CONF_HELPER_BEARER_TOKEN: "required"}


@pytest.mark.asyncio
async def test_malformed_target_mapping_is_rejected():
    """Options reject malformed mapping JSON instead of persisting it."""
    flow = ConfigFlow.async_get_options_flow(_entry())

    result = await flow.async_step_init(
        {
            CONF_HELPER_BASE_URL: "https://helper.example",
            CONF_AIRPLAY_TARGETS: "not-json",
            CONF_HELPER_BEARER_TOKEN: "fixture-token",
        }
    )

    assert result["type"] == "form"
    assert result["errors"] == {CONF_AIRPLAY_TARGETS: "invalid_target_mapping"}


@pytest.mark.asyncio
async def test_duplicate_target_mapping_keys_are_rejected():
    """Options reject ambiguous duplicate zone records."""
    valid_mapping = _target_mapping_json()
    duplicate_mapping = "{" + valid_mapping[1:-1] + "," + valid_mapping[1:-1] + "}"
    flow = ConfigFlow.async_get_options_flow(_entry())

    result = await flow.async_step_init(
        {
            CONF_HELPER_BASE_URL: "https://helper.example",
            CONF_AIRPLAY_TARGETS: duplicate_mapping,
            CONF_HELPER_BEARER_TOKEN: "fixture-token",
        }
    )

    assert result["type"] == "form"
    assert result["errors"] == {CONF_AIRPLAY_TARGETS: "invalid_target_mapping"}
