# Juke Audio Home Assistant Integration

This repository contains one HACS integration for Juke Audio multi-zone amplifiers.
The integration owns the Juke connection, zone controls, routing services, and the
optional direct RAOP sender. There is no separate helper service to install or
configure.

## Install HACS

If you have not yet installed HACS, follow the instructions at
[https://hacs.xyz](https://hacs.xyz/).

## Install the Juke Audio integration

You can install this repository manually or through HACS. In Home Assistant:

1. Select **Settings → Devices & services → Add integration**.
2. Search for **Juke Audio** and add the integration.
3. Enter the Juke amplifier host, administrator credentials, and scan interval.

## Configuration

- **Host:** IP address or hostname of the Juke amplifier. The default is
  `juke.local`, which may not resolve on every network.
- **Username:** `Admin` is the default Juke username.
- **Password:** The password configured in the amplifier's Administrator
  Settings.
- **Scan interval:** How often Home Assistant fetches values from the amplifier.

The integration creates media-player entities for amplifier zones and inputs,
plus diagnostic sensors. Zone entities expose Juke source selection, volume, and
mute controls. Input entities expose the input types supported by the Juke.

## Optional integrated RAOP playback

The integration can stream an already reachable media URL directly through
`pyatv==0.18.0`. RAOP playback is opt-in: the **Options** flow accepts one JSON
object containing explicit serialized receiver mappings. Example shape:

```json
{
  "zone-1": {
    "zone_id": "zone-1",
    "host": "receiver.example",
    "port": 7000,
    "device_id": "AA:BB:CC:DD:EE:01",
    "player_uuid": "player-1",
    "service_name": "Living Receiver",
    "txt": {
      "deviceid": "AA:BB:CC:DD:EE:01",
      "sr": "44100"
    },
    "protocol_mode": "raop_fallback"
  }
}
```

The mapping key and `zone_id` must be the exact Juke zone ID. The sender builds a
`pyatv` `ManualService` from that mapping; it performs no receiver discovery,
name matching, DNS allowlisting, or fallback target inference. Only mappings
with `protocol_mode` set to `raop_fallback` advertise `PLAY_MEDIA`.

Direct media IDs must be absolute `http://` or `https://` URLs. The integration
rejects credentials, malformed ports, localhost, loopback addresses, and legacy
numeric loopback forms before loading `pyatv`. `pyatv` retrieves the approved
URL; this integration does not add a downloader or media cache. Playback is
asynchronous and cancellable and does not change the Juke source, routing,
volume, mute, or state cache.

`airplay2` is reserved for future sender work. It is currently unproven and is
not advertised or sent by this integration.

## Requirements

- Minimum Juke firmware version 4.2.1
- `jukeaudio==0.0.11`
- `pyatv==0.18.0` (only needed when integrated RAOP playback is used)
