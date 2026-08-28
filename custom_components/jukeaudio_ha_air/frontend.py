"""Bundled Home Assistant frontend for the Juke control panel."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components import frontend as ha_frontend
from homeassistant.core import HomeAssistant

from .const import DOMAIN

try:
    from homeassistant.components.http import StaticPathConfig
except ImportError:  # Home Assistant before the batched static-path API.
    StaticPathConfig = None

PANEL_COMPONENT = "juke-audio-panel"
PANEL_URL_PATH = "juke-audio-control"
STATIC_URL = f"/{DOMAIN}/juke-audio.js"
_DATA_FRONTEND_REGISTERED = "_frontend_registered"


async def async_register_frontend(hass: HomeAssistant) -> None:
    """Serve and load the Juke panel once for this Home Assistant runtime."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get(_DATA_FRONTEND_REGISTERED):
        return

    asset = Path(__file__).with_name("frontend") / "juke-audio.js"
    if hasattr(hass.http, "async_register_static_paths"):
        if StaticPathConfig is None:
            raise RuntimeError("Home Assistant static-path configuration is unavailable")
        await hass.http.async_register_static_paths(
            [StaticPathConfig(STATIC_URL, str(asset), cache_headers=False)]
        )
    else:
        hass.http.register_static_path(STATIC_URL, str(asset), cache_headers=False)
    ha_frontend.add_extra_js_url(hass, STATIC_URL)
    ha_frontend.async_register_built_in_panel(
        hass,
        PANEL_COMPONENT,
        sidebar_title="Juke Audio",
        sidebar_icon="mdi:music-box-multiple",
        frontend_url_path=PANEL_URL_PATH,
        config={"domain": DOMAIN},
    )
    domain_data[_DATA_FRONTEND_REGISTERED] = True


async def async_unregister_frontend(hass: HomeAssistant) -> None:
    """Remove the Juke sidebar panel after the final entry unloads."""
    domain_data = hass.data.get(DOMAIN)
    if not isinstance(domain_data, dict) or not domain_data.pop(
        _DATA_FRONTEND_REGISTERED, False
    ):
        return

    ha_frontend.async_remove_panel(
        hass, PANEL_URL_PATH, warn_if_unknown=False
    )
