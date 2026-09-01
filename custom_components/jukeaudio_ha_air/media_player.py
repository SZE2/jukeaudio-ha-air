from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .airplay import DirectRaopClient, has_raop_target
from .const import DOMAIN, LOGGER
from .hub import JukeAudioHub, JukeAudioDevice

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Setup the config entry for my device."""

    hub: JukeAudioHub = hass.data[DOMAIN][config_entry.entry_id]["hub"]
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]

    entities = []    
    for juke_id in hub.jukes:
        juke = hub.jukes[juke_id]

        # Add zone entities
        for zone_id in juke.zones:
            entities.append(
                Zone(juke, coordinator, config_entry, zone_id)
            )

    if entities:
        async_add_entities(entities)


class JukeAudioMediaPlayerBase(CoordinatorEntity, MediaPlayerEntity):
    """Base class for our zone media players"""

    _attr_has_entity_name = True

    def __init__(self, juke: JukeAudioDevice, coordinator, config_entry) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
        )
        self._juke = juke
        self._config_entry = config_entry

    @property
    def device_info(self) -> DeviceInfo:
        return self._juke.device_info

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()


class Zone(JukeAudioMediaPlayerBase):
    """Zone media player"""

    device_class = MediaPlayerDeviceClass.SPEAKER

    def __init__(self, juke: JukeAudioDevice, coordinator, config_entry, zone_id) -> None:
        """Initialize the sensor."""
        super().__init__(juke, coordinator, config_entry)
        self._zone_id = zone_id

    @property
    def unique_id(self) -> str:
        return f"zone_{self._zone_id}"

    @property
    def name(self) -> str:
        return f'{self._juke.zones[self._zone_id]["name"]} Zone'

    @property
    def extra_state_attributes(self):
        """Return additional attributes for the zone."""
        attributes = {}
        
        zone_data = self._juke.zones[self._zone_id]
        
        # Add warning messages as attributes if present
        if "warnings" in zone_data and zone_data["warnings"]:
            attributes["warnings"] = zone_data["warnings"]
            attributes["warning_count"] = len(zone_data["warnings"])

        attributes["juke_zone_id"] = self._zone_id
        attributes["juke_zone_name"] = zone_data.get("name", self._zone_id)
        attributes["juke_input_options"] = self._zone_input_options()

        return attributes
    
    @property
    def state(self) -> MediaPlayerState | None:
        """State of the player."""
        # Check if there's an active input for this zone
        zone_data = self._juke.zones[self._zone_id]

        # A disabled zone is off even if stale active-input data remains cached.
        if not zone_data.get("enabled", True):
            return MediaPlayerState.OFF

        active_input_id = zone_data.get("active_input")
        active_input = self._input_data(active_input_id) if active_input_id else None
        if active_input is not None and active_input.get("streaming", False):
            return MediaPlayerState.PLAYING

        # A selected but idle source is not playing media.
        return MediaPlayerState.ON
        
    @property
    def media_title(self) -> str | None:
        """Title of current playing media."""
        zone_data = self._juke.zones[self._zone_id]
        active_input_id = zone_data.get("active_input")
        active_input = self._input_data(active_input_id) if active_input_id else None
        if active_input is None or not active_input.get("streaming", False):
            return None

        if active_input.get("input_class") == 0:
            input_name = active_input.get("name")
            if input_name:
                return f"Playing from {input_name}"

        input_type = active_input.get("input_type", "Unknown")
        return f"Playing from {input_type}"
    
    @property
    def media_artist(self) -> str | None:
        """Artist of current playing media."""
        # If there's additional metadata available from the active input
        # you could return it here
        return None
    
    @property 
    def icon(self) -> str | None:
        zone_data = self._juke.zones[self._zone_id]
        
        # Show warning icon if there are warnings
        if "warnings" in zone_data and zone_data["warnings"]:
            return "mdi:speaker-message"
        
        """Return dynamic icon based on playing state."""
        if self.state == MediaPlayerState.PLAYING:
            return "mdi:speaker-play"
        elif self.state == MediaPlayerState.ON:
            return "mdi:speaker"
        else:
            return "mdi:speaker-off"

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        """Flag media player features that are supported."""
        features = (
            MediaPlayerEntityFeature.SELECT_SOURCE
            | MediaPlayerEntityFeature.VOLUME_SET
            | MediaPlayerEntityFeature.VOLUME_MUTE
            | MediaPlayerEntityFeature.TURN_ON
            | MediaPlayerEntityFeature.TURN_OFF
        )
        if has_raop_target(self._config_entry, self._zone_id):
            features |= MediaPlayerEntityFeature.PLAY_MEDIA
        return features

    async def async_play_media(self, media_type: str, media_id: str, **kwargs: object) -> None:
        """Stream a validated HTTP(S) media URL directly through RAOP."""
        await DirectRaopClient(self._config_entry).async_play_media(
            self._zone_id, media_id
        )

    @property
    def volume_level(self) -> float | None:
        """Volume level of the media player (0..1)."""
        return float(self._juke.zones[self._zone_id]["volume"]) / 100.0

    @property
    def is_volume_muted(self) -> bool | None:
        """Return the cached mute state of the zone."""
        return self._juke.zones[self._zone_id].get("muted")

    @staticmethod
    def _source_label(input_data) -> str:
        """Return a stable, user-facing source label for one Juke input."""
        input_class = input_data.get("input_class")
        if input_class == 1:
            return "Spotify"
        if input_class == 2:
            return "AirPlay 2"
        return input_data.get("name") or input_data.get("input_type") or "Unknown"

    def _input_data(self, input_id):
        """Read one input from the device cache or shared-input cache."""
        input_data = self._juke.inputs.get(input_id)
        if input_data is not None:
            return input_data
        return getattr(self._juke.hub, "group_inputs", {}).get(input_id)

    def _known_general_input_ids(self, source: str) -> set[str]:
        """Return unqualified general inputs with this source label."""
        candidates = set()
        input_maps = (
            self._juke.inputs,
            getattr(self._juke.hub, "group_inputs", {}),
        )
        for input_map in input_maps:
            for input_id, input_data in input_map.items():
                if (
                    input_data.get("input_class") == 0
                    and self._source_label(input_data) == source
                ):
                    candidates.add(input_id)
        return candidates

    def _zone_input_options(self) -> list[dict]:
        """Describe Juke inputs associated with this zone from cached data."""
        zone_data = self._juke.zones[self._zone_id]
        candidates = []
        for input_id in zone_data.get("input", []):
            input_data = self._input_data(input_id)
            if input_data is None:
                continue
            candidates.append((input_id, input_data, self._source_label(input_data)))

        label_counts = {}
        for _, _, label in candidates:
            label_counts[label] = label_counts.get(label, 0) + 1

        options = []
        for input_id, input_data, label in candidates:
            source = label
            if label_counts[label] > 1:
                source = f"{label} ({input_id})"
            streaming = bool(input_data.get("streaming", False))
            options.append(
                {
                    "input_id": input_id,
                    "source": source,
                    "input_type": input_data.get("input_type", "Unknown"),
                    "enabled": bool(input_data.get("enabled", True)),
                    "streaming": streaming,
                    "selectable": bool(input_data.get("enabled", True)) and streaming,
                }
            )
        return options

    @property
    def source_list(self) -> list[str]:
        """List inputs Juke currently exposes as selectable for this zone."""
        return [
            option["source"]
            for option in self._zone_input_options()
            if option["selectable"]
        ]

    @property
    def source(self) -> str | None:
        """Return Juke's actual active input for this zone."""
        active_input_id = self._juke.zones[self._zone_id].get("active_input")
        if active_input_id is None:
            return None

        for option in self._zone_input_options():
            if option["input_id"] == active_input_id:
                return option["source"]

        input_data = self._input_data(active_input_id)
        if input_data is not None:
            return self._source_label(input_data)
        return None

    @property
    def media_content_type(self):
        """Content type of current playing media."""
        return MediaType.MUSIC

    async def async_set_volume_level(self, volume):
        """Set volume level, range 0..1."""
        LOGGER.debug("Setting volume to %s for zone %s", volume, self._zone_id)
        await self._juke.hub.set_zone_volume(self._zone_id, int(volume*100))
        await self.async_update()

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute or unmute the zone without changing its volume."""
        LOGGER.debug("Setting mute to %s for zone %s", mute, self._zone_id)
        await self._juke.hub.set_zone_mute(self._zone_id, mute)
        await self.async_update()

    async def async_select_source(self, source: str):
        """Select one source Juke currently permits for this zone."""
        selected = next(
            (option for option in self._zone_input_options() if option["source"] == source),
            None,
        )
        if selected is None:
            known_general_inputs = self._known_general_input_ids(source)
            if len(known_general_inputs) == 1:
                zone_name = self._juke.zones[self._zone_id].get("name", self._zone_id)
                raise HomeAssistantError(
                    f"Source is not routed to zone {zone_name}; enable its route before selecting it"
                )
            raise HomeAssistantError(f"Unknown source for this zone: {source}")
        if not selected["selectable"]:
            raise HomeAssistantError(
                f"Source is not currently selectable: {source}"
            )

        LOGGER.debug("Selecting input %s for zone %s", selected["input_id"], self._zone_id)
        await self._juke.hub.set_active_input(self._zone_id, selected["input_id"])

    async def async_turn_on(self) -> None:
        """Enable this physical Juke zone."""
        await self._juke.hub.set_zone_enabled(self._zone_id, True)

    async def async_turn_off(self) -> None:
        """Disable this physical Juke zone."""
        await self._juke.hub.set_zone_enabled(self._zone_id, False)


class InputMediaPlayer(JukeAudioMediaPlayerBase):
    """Input media player"""
    
    device_class = MediaPlayerDeviceClass.RECEIVER
    
    def __init__(self, juke: JukeAudioDevice, coordinator, config_entry, input_id) -> None:
        """Initialize the input media player."""
        super().__init__(juke, coordinator, config_entry)
        self._input_id = input_id
    
    @property
    def unique_id(self) -> str:
        return f"input_{self._input_id}"
    
    @property
    def name(self) -> str:
        return f"{self._juke.inputs[self._input_id]['name']} Input"
    
    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        """Flag media player features that are supported."""
        features = MediaPlayerEntityFeature.SELECT_SOURCE | MediaPlayerEntityFeature.TURN_ON | MediaPlayerEntityFeature.TURN_OFF
        
        # Only add volume control if volume exists for this input
        input_data = self._juke.inputs[self._input_id]
        if "volume" in input_data and input_data["volume"] is not None:
            features |= MediaPlayerEntityFeature.VOLUME_SET
            
        return features
    
    @property
    def state(self) -> MediaPlayerState | None:
        """State of the player."""
        input_data = self._juke.inputs[self._input_id]
        # Check if input is enabled, defaulting to True if not present
        if input_data.get("enabled", True):
            return MediaPlayerState.ON
        else:
            return MediaPlayerState.OFF
    
    @property
    def volume_level(self) -> float | None:
        """Volume level of the media player (0..1)."""
        input_data = self._juke.inputs[self._input_id]
        if "volume" in input_data and input_data["volume"] is not None:
            return float(input_data["volume"]) / 100.0
        return None
    
    @property
    def source(self) -> str:
        """Currently selected input type."""
        return self._juke.inputs[self._input_id]["input_type"]
    
    @property
    def source_list(self) -> list[str]:
        """List of available input types."""
        available_types = self._juke.inputs[self._input_id]["available_types"]
        
        # Get current source by using the source property
        current_source = self.source
        
        # Add current source if not already in the list
        if current_source and current_source not in available_types:
            return available_types + [current_source]
        
        return available_types
    
    @property
    def icon(self):
        """Return dynamic icon based on input type."""
        input_type = self.source
        
        # Map input types to appropriate icons
        icon_map = {
            "Airplay2": "mdi:cast-audio-variant",
            "DLNA": "mdi:cast-audio",
            "Spotify": "mdi:spotify",
            "USB-1": "mdi:usb",
            "USB-2": "mdi:usb",
            "Bluetooth": "mdi:bluetooth-audio",
            "RCA": "mdi:audio-input-rca",
            "Optical": "mdi:laser-pointer"
        }
        
        # Return the mapped icon or a default
        return icon_map.get(input_type, "mdi:music-box")
    
    async def async_set_volume_level(self, volume):
        """Set volume level, range 0..1."""
        LOGGER.debug("Setting volume to %s for input %s", volume, self._input_id)
        await self._juke.hub.set_input_volume(self._input_id, int(volume*100))
        await self.async_update()
    
    async def async_select_source(self, source: str):
        """Select input type."""
        LOGGER.debug("Setting input type to %s for input %s", source, self._input_id)
        await self._juke.hub.set_input_type(self._input_id, source)
        await self.async_update()
    
    async def async_turn_on(self) -> None:
        """Turn the input on (enable it)."""
        LOGGER.debug("Enabling input %s", self._input_id)
        await self._juke.hub.set_input_enabled(self._input_id, True)
        await self.async_update()
    
    async def async_turn_off(self) -> None:
        """Turn the input off (disable it)."""
        LOGGER.debug("Disabling input %s", self._input_id)
        await self._juke.hub.set_input_enabled(self._input_id, False)
        await self.async_update()
