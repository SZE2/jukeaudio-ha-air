# Juke Audio Home Assistant Integration — Experimental Fork

> [!WARNING]
> **Work in progress — do not rely on this fork for normal use, production
> automations, or unattended audio.** It is an experimental fork of
> [pkarimov/jukeaudio_ha](https://github.com/pkarimov/jukeaudio_ha), created to
> develop and assess optional in-process RAOP playback. For a supported baseline,
> installation guidance, and ordinary Juke control, use the
> [original Juke Audio integration](https://github.com/pkarimov/jukeaudio_ha).
>
> This repository is not affiliated with or endorsed by the original author.
>
> **Do not open issues or request support from the original project for this
> fork's experimental changes.**

This repository contains one **separately installable** HACS integration for Juke
Audio multi-zone amplifiers. Its Home Assistant domain is
`jukeaudio_ha_air`, intentionally distinct from the upstream
`jukeaudio_ha` domain, so the experimental fork never shares or overwrites the
upstream component directory. The fork retains Juke connection, zone controls,
and routing behavior while adding an experimental optional direct RAOP sender.
There is no separate helper service to install or configure.

> [!IMPORTANT]
> This fork requires its own Home Assistant config entry. Do not run its Juke
> controls alongside an upstream Juke entry in normal use: both entries expose
> the same physical amplifier. The distinct domain prevents file collisions; it
> does not make duplicate control planes desirable.

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

The integration creates media-player entities only for physical amplifier zones,
plus diagnostic sensors. Zone entities expose Juke source selection, power,
volume, and mute controls. General inputs are configuration/routing controls:
an enable switch, an input-type select, and additive input-to-zone route switches.
They deliberately are not playback targets for TTS or `media_player.play_media`.

Zone source selection accepts only inputs that Juke currently reports as both
routed to that zone and streaming. For an automation, enable the matching
input-to-zone route first; an inactive or unrouted source is deliberately
rejected rather than forced onto the zone.

## Bundled Juke control panel

After the integration's first config entry loads, it automatically exposes a
sidebar panel at **Juke Audio** (`/juke-audio-control`). The panel and its
frontend asset ship inside this HACS integration; no separate custom-card
repository or Lovelace resource registration is required.

The panel discovers Juke entities from their integration attributes and shows:

- every physical zone with its selected source, power control, and all
  Juke-routed source candidates;
- a pulse on a candidate only when Juke reports it as `streaming`;
- a selectable candidate only when it is enabled and Juke reports it as
  streaming; and
- general-input enable, type, and per-zone route controls separately from
  audio playback.

Selecting a source always calls Juke's active-input operation only. Route
changes remain explicit input-to-zone controls, so an automation must follow
the safe order: **add route → wait for refresh → select a Juke-selectable
streaming source → perform the separately configured transport action →
restore/remove routes as desired**.

The bundled `custom:juke-zone-card` is also registered automatically for an
owner-created Lovelace dashboard. The card uses the same Juke-reported
availability rules as the panel; it never makes a non-streaming or disabled
source clickable.

> [!CAUTION]
> Juke remains the source of truth for zone selection and playback state. Some
> Juke firmware versions can retain a DLNA input's `streaming` indication after
> the renderer has become idle. This integration deliberately passes through
> Juke's reported state instead of trying to reset, mask, or infer around it, so
> a real DLNA session is never interrupted by Home Assistant.

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
