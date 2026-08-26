# Isolated legacy RAOP helper

This directory is a separately managed, source-only fallback sender. It is not
part of the HACS custom component and does not import Home Assistant, Music
Assistant, Juke API code, or any discovery/client code. The helper has no HTTP
service, daemon, config flow, persistent credential store, or entity changes.

## Direct mapping only

Provide a JSON object keyed by the exact Juke `zone_id`. Every record must
contain the immutable explicit fields below; the mapping key must equal
`zone_id`. The helper never infers a zone from a display name, service name,
host/IP address, ordering, or discovered service.

```json
{
  "zone-6": {
    "zone_id": "zone-6",
    "host": "YOUR_ZONE_6_RAOP_HOST",
    "port": 7000,
    "device_id": "YOUR_ZONE_6_DEVICE_ID",
    "player_uuid": "YOUR_ZONE_6_PLAYER_UUID",
    "service_name": "YOUR_ZONE_6_SERVICE_NAME",
    "txt": {
      "deviceid": "YOUR_ZONE_6_DEVICE_ID",
      "ch": "2",
      "cn": "0,1",
      "sr": "44100"
    },
    "protocol_mode": "raop_fallback"
  }
}
```

`airplay2` records may be preserved by the shared mapping contract, but this
helper rejects them when selecting a sender target. This package is RAOP-only
and legacy; it does not claim native AirPlay 2 support.

## Dependency and one-shot use

The helper-only dependency is pinned in `requirements.txt`:

```text
pyatv==0.18.0
```

Install that dependency in the environment managed for this helper, then run a
single explicit local WAV file and exact zone mapping:

```text
python -m airplay_helper \
  --targets-file <TARGETS_FILE> \
  --zone-id <ZONE_6_ID> \
  --wav-file <WAV_FILE>
```

For a local Zone-6-only manual test, replace every placeholder with values from
your own local setup. Do not use discovery or another zone:

```text
python -m airplay_helper --targets-file <LOCAL_ZONE_6_TARGETS_JSON> --zone-id <LOCAL_ZONE_6_ID> --wav-file <LOCAL_TEST_WAV>
```

The command connects with pyatv's `ManualService` in RAOP mode, streams the
specified file once, and closes the connection. For the explicitly mapped Juke
receiver whose `txt["model"]` is exactly `Shairport Sync`, the helper tolerates
only the exact built-in `RuntimeError("not connected to remote")` raised from
`receiver.stream.stream_file` at the observed pyatv 0.18 post-transfer RTSP
teardown boundary. pyatv 0.18 does not expose a transfer-complete callback before
that internal teardown; the source tests use an injected completion marker to
exercise the boundary. Setup failures, pre-transfer stream failures, other
models, other errors, and generic `ConnectionError` remain failures. This is a
narrow Juke/receiver-specific RAOP teardown compatibility behavior and does not
prove audible output. Native AirPlay 2 (AP2) remains unsupported. No live device
test is part of this source package's automated verification.
