"""Bundled Home Assistant frontend for the Juke control panel."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components import frontend as ha_frontend
from homeassistant.core import HomeAssistant

from .const import DOMAIN

PANEL_COMPONENT = "juke-audio-panel"
PANEL_URL_PATH = "juke-audio-control"
STATIC_URL = f"/{DOMAIN}/juke-audio.js"
_DATA_FRONTEND_REGISTERED = "_frontend_registered"


def async_register_frontend(hass: HomeAssistant) -> None:
    """Serve and load the Juke panel once for this Home Assistant runtime."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get(_DATA_FRONTEND_REGISTERED):
        return

    asset = Path(__file__).with_name("frontend") / "juke-audio.js"
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
