"""Hub for Juke Audio"""
from collections.abc import Mapping

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo

from .juke_client import JukeAudioClientV3

from .const import DOMAIN, LOGGER


class JukeAudioHub:
    """Hub class for Juke Audio"""

    def __init__(
        self,
        hass: HomeAssistant,
        ip_address: str,
        username: str,
        password: str,
    ) -> None:
        self._hass = hass
        self._ip_address = ip_address
        self._username = username
        self._password = password
        self.jukes = {}
        self.group_inputs = {}
        self.client = None
        self.coordinator = None
        self._server_device_id = None

    async def verify_connection(self) -> bool:
        """Test if we can connect to the host."""
        client = JukeAudioClientV3()
        if await client.can_connect_to_juke(self._ip_address):
            self.client = client
            return True
        else:
            return False

    async def get_devices(self):
        """Test if we can authenticate to the host."""
        return await self.client.get_devices(self._ip_address, self._username, self._password)

    async def initialize(self):
        """Initialize hub"""
        self._server_device_id = await self.client.get_server_device_id(
            self._ip_address, self._username, self._password)

    async def get_connection_info(self):
        """Get connection info"""
        return await self.client.get_device_connection_info(
            self._ip_address, self._username, self._password, self._server_device_id
        )

    async def _get_devices_info(self):
        """Get devices info"""
        return await self.client.get_devices_info(
            self._ip_address, self._username, self._password
        )

    async def _get_zones_ids(self):
        """Get zones"""
        zones = await self.client.get_zones(self._ip_address, self._username, self._password)
        return zones["zone_ids"]
    
    async def _get_zones_info(self):
        """Get zones"""
        zones = await self.client.get_zones_info(self._ip_address, self._username, self._password)
        return zones

    async def _get_zone_config(self, zone_id: str):
        """Get zone config"""
        return await self.client.get_zone_config(
            self._ip_address, self._username, self._password, zone_id
        )

    def _get_coordinator(self):
        """Return the coordinator associated with this hub, when available."""
        if self.coordinator is not None:
            return self.coordinator
        if self._hass is None:
            return None
        for entry_data in getattr(self._hass, "data", {}).get(DOMAIN, {}).values():
            if entry_data.get("hub") is self:
                return entry_data.get("coordinator")
        return None

    async def _refresh_after_write(self) -> None:
        """Refresh coordinator-backed state after a successful write."""
        coordinator = self._get_coordinator()
        if coordinator is not None:
            await coordinator.async_request_refresh()

    async def set_zone_mute(self, zone_id: str, muted: bool):
        """Mute or unmute a zone without changing its volume."""
        result = await self.client.set_zone_mute(
            self._ip_address, self._username, self._password, zone_id, muted
        )
        await self._refresh_after_write()
        return result

    async def set_zone_enabled(self, zone_id: str, enabled: bool):
        """Enable or disable a zone."""
        result = await self.client.set_zone_enabled(
            self._ip_address, self._username, self._password, zone_id, enabled
        )
        await self._refresh_after_write()
        return result

    async def set_zone_inputs(self, zone_id: str, input_ids: list[str]):
        """Replace the inputs assigned to a zone."""
        result = await self.client.set_zone_inputs(
            self._ip_address, self._username, self._password, zone_id, input_ids
        )
        await self._refresh_after_write()
        return result

    async def add_input_zone(self, input_id: str, zone_id: str):
        """Add a zone to an input without replacing other memberships."""
        result = await self.client.add_input_zone(
            self._ip_address, self._username, self._password, input_id, zone_id
        )
        await self._refresh_after_write()
        return result

    async def remove_input_zone(self, input_id: str, zone_id: str):
        """Remove a zone from an input without changing other memberships."""
        result = await self.client.remove_input_zone(
            self._ip_address, self._username, self._password, input_id, zone_id
        )
        await self._refresh_after_write()
        return result

    async def set_input_zones(self, input_id: str, zone_ids: list[str]):
        """Replace only one general input's complete zone route set.

        The v3 client exposes scoped add/remove membership operations rather than
        a whole-input replacement endpoint. Compose those operations here so
        mappings for every other input remain untouched, and refresh once after
        the complete successful write sequence.
        """
        input_info = self.group_inputs.get(input_id)
        if input_info is None:
            raise ValueError(f"Unknown input: {input_id}")
        if input_info.get("input_class") != 0:
            raise ValueError(f"Input is not a general input: {input_id}")
        if len(zone_ids) != len(set(zone_ids)):
            raise ValueError("Duplicate zone IDs")

        current_zones = input_info.get("zones", ()) or ()
        if isinstance(current_zones, Mapping):
            current_zones = current_zones.get(
                "zone_ids", current_zones.get("zones", ())
            ) or ()
        current_ids = []
        for zone in current_zones:
            zone_id = (
                zone
                if isinstance(zone, str)
                else zone.get("zone_id", zone.get("id"))
            )
            if isinstance(zone_id, str) and zone_id not in current_ids:
                current_ids.append(zone_id)
        current_set = set(current_ids)
        desired_ids = list(dict.fromkeys(zone_ids))
        desired_set = set(desired_ids)
        results = []

        for zone_id in current_ids:
            if zone_id not in desired_set:
                results.append(
                    await self.client.remove_input_zone(
                        self._ip_address,
                        self._username,
                        self._password,
                        input_id,
                        zone_id,
                    )
                )
        for zone_id in desired_ids:
            if zone_id not in current_set:
                results.append(
                    await self.client.add_input_zone(
                        self._ip_address,
                        self._username,
                        self._password,
                        input_id,
                        zone_id,
                    )
                )

        if results:
            await self._refresh_after_write()
        return results[-1] if results else None

    async def get_active_input(self, zone_id: str):
        """Read the active input for a zone."""
        return await self.client.get_active_input(
            self._ip_address, self._username, self._password, zone_id
        )

    async def set_active_input(self, zone_id: str, input_id: str):
        """Select the active input for a zone."""
        result = await self.client.set_active_input(
            self._ip_address, self._username, self._password, zone_id, input_id
        )
        await self._refresh_after_write()
        return result

    async def get_streaming_inputs(self, zone_id: str):
        """Read streaming inputs associated with a zone."""
        return await self.client.get_streaming_inputs(
            self._ip_address, self._username, self._password, zone_id
        )

    async def set_zone_based_input_enabled(
        self, zone_id: str, input_type: str, enabled: bool
    ):
        """Enable or disable a supported native zone-based input type."""
        result = await self.client.set_zone_based_input_enabled(
            self._ip_address,
            self._username,
            self._password,
            zone_id,
            input_type,
            enabled,
        )
        await self._refresh_after_write()
        return result

    async def set_zone_input(self, zone_id: str, input):
        """Set zone inputs"""
        return await self.client.set_zone_input(
            self._ip_address, self._username, self._password, zone_id, input
        )
    
    async def set_zone_volume(self,zone_id: str, volume: int):
        """Set zone volume"""
        return await self.client.set_zone_volume(
            self._ip_address, self._username, self._password, zone_id, volume
        )

    async def _get_input_ids(self):
        """Get inputs"""
        inputs = await self.client.get_inputs(self._ip_address, self._username, self._password)
        return inputs["input_ids"]
    
    async def _get_input_info(self):
        """Get inputs"""
        inputs = await self.client.get_inputs_info(self._ip_address, self._username, self._password)
        return inputs

    async def _get_input_config(self, input_id: str):
        """Get input config"""
        return await self.client.get_input_config(
            self._ip_address, self._username, self._password, input_id
        )

    async def _get_available_inputs(self, input_id: str):
        """Get available inputs"""
        return await self.client.get_available_inputs(
            self._ip_address, self._username, self._password, input_id
        )
    
    async def set_input_type(self, input_id: str, type: str):
        """Set input type"""
        return await self.client.set_input_type(
            self._ip_address, self._username, self._password, input_id, type
        )

    async def set_input_volume(self, input_id: str, volume: int):
        """Set the volume for a specific input (0-100)."""
        return await self.client.set_input_volume(
            self._ip_address, self._username, self._password, input_id, volume
        )

    async def set_input_enabled(self, input_id: str, enabled: bool):
        """Enable or disable a specific input."""
        return await self.client.enable_input(
            self._ip_address, self._username, self._password, input_id, enabled
        )   

    async def fetch_data(self):
        if self.client is None:
            can_connect = await self.verify_connection()
            if not can_connect:
                LOGGER.error("Could not connect to Juke Audio")
                return

        return await self._fetch_data_v3()

    async def _fetch_data_v3(self):
        """Get the data from Juke"""
        devices = await self._get_devices_info()
        LOGGER.debug("Juke devices info: %s", devices)

        for device in devices:
            if self.jukes.get(device["device_id"]) is None:
                self.jukes[device["device_id"]] = JukeAudioDevice(self)
                LOGGER.debug("Initialized JukeAudioDevice for %s", device["device_id"])
            
            self.jukes[device["device_id"]].update(device)

        zones = await self._get_zones_info()
        LOGGER.debug("Juke zone info: %s", zones)

        for z in zones:
            zone_id_parts = z["zone_id"].split("-")
            zone_device_id = zone_id_parts[0]+"-"+zone_id_parts[1]
            if self.jukes.get(zone_device_id) is not None:
                juke = self.jukes[zone_device_id]
                juke.zones[z["zone_id"]] = z

        inputs = await self._get_input_info()
        LOGGER.debug("Juke input info: %s", inputs)

        for i in inputs:
            input_id_parts = i["input_id"].split("-")
            input_device_id = input_id_parts[0]+"-"+input_id_parts[1]
            if self.jukes.get(input_device_id) is not None:
                juke = self.jukes[input_device_id]
                juke.inputs[i["input_id"]] = i

            if i["input_class"] == 0:
                self.group_inputs[i["input_id"]] = i

class JukeAudioDevice:
    """HA device for Juke Audio"""

    def update(self, device_info) -> None:
        """Update device information"""
        self._device_id = device_info["device_id"]
        self.config = device_info["config"]
        self.connection_info = device_info["connection"]
        self.device_metrics = device_info["metrics"]
        self.device_attributes = device_info["attributes"]
        self.uid_base = self.device_attributes["serial_number"]
        self.zones = {}
        self.inputs = {}

    def __init__(self, hub: JukeAudioHub) -> None:
        self.hub = hub

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info"""
        name = self.config["name"]
        if name is None or name == "":
            name = self._device_id

        return {
            "identifiers": {(DOMAIN, f"{self.device_attributes['serial_number']}")},
            "name": name,
            "manufacturer": "Juke Audio",
            "sw_version": self.device_attributes["firmware_version"],
        }