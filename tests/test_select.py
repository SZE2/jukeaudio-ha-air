"""Tests for Juke general-input configuration selects."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.jukeaudio_ha_air.const import DOMAIN
from custom_components.jukeaudio_ha_air.select import InputTypeSelect, async_setup_entry


class _FakeHub:
    def __init__(self) -> None:
        self.calls = []
        self.group_inputs = {
            "input-0": {
                "input_id": "input-0",
                "input_class": 0,
                "name": "Juke Bluetooth",
                "input_type": "Airplay2",
                "available_types": ["Airplay2", "Spotify", "Bluetooth"],
            }
        }
        self.jukes = {
            "amp-1": SimpleNamespace(
                device_info={"identifiers": {(DOMAIN, "amp-1")}},
                inputs=dict(self.group_inputs),
            )
        }

    async def set_input_type(self, input_id, input_type):
        self.calls.append(("set_input_type", input_id, input_type))


def _make_hass(hub: _FakeHub):
    return SimpleNamespace(
        data={
            DOMAIN: {
                "entry-1": {
                    "hub": hub,
                    "coordinator": SimpleNamespace(),
                }
            }
        }
    )


@pytest.mark.asyncio
async def test_general_input_type_select_exposes_only_juke_available_types():
    """Input type configuration is a select, not a pretend playback source."""
    hub = _FakeHub()
    entry = SimpleNamespace(entry_id="entry-1")
    entities = []

    await async_setup_entry(_make_hass(hub), entry, entities.extend)

    assert len(entities) == 1
    selector = entities[0]
    assert isinstance(selector, InputTypeSelect)
    assert selector.unique_id == "input_type_input-0"
    assert selector.current_option == "Airplay2"
    assert selector.options == ["Airplay2", "Spotify", "Bluetooth"]


@pytest.mark.asyncio
async def test_group_only_general_input_still_gets_a_type_select():
    """Shared general inputs remain configurable without a per-device cache copy."""
    hub = _FakeHub()
    hub.jukes = {}
    entry = SimpleNamespace(entry_id="entry-1")
    entities = []

    await async_setup_entry(_make_hass(hub), entry, entities.extend)

    assert [entity.unique_id for entity in entities] == ["input_type_input-0"]
    assert entities[0].device_info is None


def test_type_select_exposes_stable_dashboard_control_metadata():
    """The bundled panel can identify type selectors without parsing names."""
    hub = _FakeHub()
    selector = InputTypeSelect(
        hub,
        hub.jukes["amp-1"],
        SimpleNamespace(),
        "input-0",
    )

    assert selector.extra_state_attributes == {
        "juke_entity_role": "input_type",
        "juke_input_id": "input-0",
        "juke_input_name": "Juke Bluetooth",
    }


@pytest.mark.asyncio
async def test_selecting_the_current_input_type_is_a_noop():
    """The UI never sends Juke a redundant type write that can return HTTP 400."""
    hub = _FakeHub()
    selector = InputTypeSelect(
        hub,
        hub.jukes["amp-1"],
        SimpleNamespace(),
        "input-0",
    )

    await selector.async_select_option("Airplay2")

    assert hub.calls == []


@pytest.mark.asyncio
async def test_selecting_an_available_input_type_uses_only_the_input_type_operation():
    """Changing a general-input type does not use media-player source services."""
    hub = _FakeHub()
    selector = InputTypeSelect(
        hub,
        hub.jukes["amp-1"],
        SimpleNamespace(),
        "input-0",
    )

    await selector.async_select_option("Spotify")

    assert hub.calls == [("set_input_type", "input-0", "Spotify")]


@pytest.mark.asyncio
async def test_input_type_select_rejects_a_type_not_exposed_by_juke():
    """The integration fails locally rather than sending an invalid type to Juke."""
    hub = _FakeHub()
    selector = InputTypeSelect(
        hub,
        hub.jukes["amp-1"],
        SimpleNamespace(),
        "input-0",
    )

    with pytest.raises(HomeAssistantError, match="not available"):
        await selector.async_select_option("DLNA")

    assert hub.calls == []


def test_select_platform_is_registered_without_removing_existing_platforms():
    """The input type selector loads alongside zones and routing switches."""
    from homeassistant.const import Platform

    from custom_components.jukeaudio_ha_air import PLATFORMS

    assert Platform.SELECT in PLATFORMS
