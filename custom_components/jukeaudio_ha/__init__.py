"""The Juke Audio integration."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta

import async_timeout
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform, CONF_HOST, CONF_USERNAME, CONF_PASSWORD, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, LOGGER
from .hub import JukeAudioHub
from .services import async_setup_services, async_unload_services
from jukeaudio.exceptions import AuthenticationException, UnexpectedException

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.MEDIA_PLAYER, Platform.SWITCH]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Juke Audio from a config entry."""

    hub = JukeAudioHub(
        hass,
        entry.data[CONF_HOST],
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
    )

    if not await hub.verify_connection():
        return False

    await hub.initialize()

    coordinator = JukeUpdateCoordinator(hass, hub, entry.data[CONF_SCAN_INTERVAL] if CONF_SCAN_INTERVAL in entry.data else 30)
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {"hub": hub, "coordinator": coordinator}

    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await async_setup_services(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
        if not any(
            isinstance(entry_data, Mapping) and "hub" in entry_data
            for entry_data in hass.data[DOMAIN].values()
        ):
            await async_unload_services(hass)

    return unload_ok


class JukeUpdateCoordinator(DataUpdateCoordinator):
    """Juke data update coordinator."""

    def __init__(self, hass: HomeAssistant, hub: JukeAudioHub, update_interval: int) -> None:
        """Initialize my coordinator."""
        super().__init__(
            hass,
            LOGGER,
            # Name of the data. For logging purposes.
            name="Juke Audio Coordinator",
            # Polling interval. Will only be polled if there are subscribers.
            update_interval=timedelta(seconds=update_interval),
        )
        LOGGER.debug("Juke data update interval: %s seconds", update_interval)
        self._hub = hub

    async def _async_update_data(self):
        """Fetch data from API endpoint.

        This is the place to pre-process the data to lookup tables
        so entities can quickly look up their data.
        """
        try:
            # Note: asyncio.TimeoutError and aiohttp.ClientError are already
            # handled by the data update coordinator.
            async with async_timeout.timeout(60):
                return await self._hub.fetch_data()
        except AuthenticationException as err:
            # Raising ConfigEntryAuthFailed will cancel future updates
            # and start a config flow with SOURCE_REAUTH (async_step_reauth)
            raise ConfigEntryAuthFailed from err
        except UnexpectedException as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err
