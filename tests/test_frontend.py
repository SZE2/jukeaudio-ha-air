"""Tests for the bundled Juke frontend panel and Lovelace card asset."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from custom_components.jukeaudio_ha_air.const import DOMAIN
from custom_components.jukeaudio_ha_air import frontend as frontend_module
from custom_components.jukeaudio_ha_air.frontend import (
    PANEL_COMPONENT,
    PANEL_URL_PATH,
    STATIC_URL,
    async_register_frontend,
)


class _FakeHttp:
    def __init__(self) -> None:
        self.calls = []

    def register_static_path(self, url_path, path, cache_headers=True) -> None:
        self.calls.append((url_path, path, cache_headers))


class _ModernFakeHttp:
    def __init__(self) -> None:
        self.calls = []

    async def async_register_static_paths(self, paths) -> None:
        self.calls.append(paths)


@pytest.mark.asyncio
async def test_frontend_registration_is_idempotent_and_registers_the_bundled_panel(
    monkeypatch,
):
    """One integration runtime serves and loads one built-in Juke control panel."""
    module_urls = []
    panels = []
    hass = SimpleNamespace(data={DOMAIN: {}}, http=_FakeHttp())

    monkeypatch.setattr(
        "custom_components.jukeaudio_ha_air.frontend.ha_frontend.add_extra_js_url",
        lambda _hass, url: module_urls.append(url),
    )
    monkeypatch.setattr(
        "custom_components.jukeaudio_ha_air.frontend.ha_frontend.async_register_built_in_panel",
        lambda _hass, component_name, **kwargs: panels.append((component_name, kwargs)),
    )

    await async_register_frontend(hass)
    await async_register_frontend(hass)

    assert len(hass.http.calls) == 1
    assert hass.http.calls[0][0] == STATIC_URL
    assert hass.http.calls[0][2] is False
    assert module_urls == [STATIC_URL]
    assert panels == [
        (
            PANEL_COMPONENT,
            {
                "sidebar_title": "Juke Audio",
                "sidebar_icon": "mdi:music-box-multiple",
                "frontend_url_path": PANEL_URL_PATH,
                "config": {"domain": DOMAIN},
            },
        )
    ]


@pytest.mark.asyncio
async def test_frontend_registration_uses_the_current_async_static_path_api(
    monkeypatch,
):
    """Current Home Assistant releases require batched async static paths."""
    module_urls = []
    panels = []
    hass = SimpleNamespace(data={DOMAIN: {}}, http=_ModernFakeHttp())

    monkeypatch.setattr(
        frontend_module,
        "StaticPathConfig",
        lambda url_path, path, cache_headers: (url_path, path, cache_headers),
    )
    monkeypatch.setattr(
        "custom_components.jukeaudio_ha_air.frontend.ha_frontend.add_extra_js_url",
        lambda _hass, url: module_urls.append(url),
    )
    monkeypatch.setattr(
        "custom_components.jukeaudio_ha_air.frontend.ha_frontend.async_register_built_in_panel",
        lambda _hass, component_name, **kwargs: panels.append((component_name, kwargs)),
    )

    await async_register_frontend(hass)

    assert hass.http.calls == [[(STATIC_URL, str(Path(frontend_module.__file__).with_name("frontend") / "juke-audio.js"), False)]]
    assert module_urls == [STATIC_URL]
    assert panels[0][0] == PANEL_COMPONENT


def test_bundled_javascript_defines_the_zone_card_and_control_panel():
    """The HACS integration ships the two frontend elements it registers."""
    asset = (
        Path(__file__).parent.parent
        / "custom_components"
        / DOMAIN
        / "frontend"
        / "juke-audio.js"
    )

    source = asset.read_text(encoding="utf-8")

    assert "customElements.define(JUKE_ZONE_CARD" in source
    assert "customElements.define(JUKE_AUDIO_PANEL" in source
    assert "juke_input_options" in source
    assert "media_player" in source
    assert "select_source" in source
