# Isolated legacy RAOP helper

This directory is a separately managed, source-only fallback sender. It is not
part of the HACS custom component and does not import Home Assistant, Music
Assistant, Juke API code, or any discovery/client code. The helper has no
persistent credential store, config flow, or entity changes. Its optional HTTP
control plane is defined in `server.py` and remains RAOP-only.

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
aiohttp>=3.9,<4
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

## Local HTTP control plane

The control plane accepts only a strict exact `zone_id` and an absolute
`http://` or `https://` media URL whose hostname is in the explicitly supplied
allowlist. It rejects loopback hosts, including legacy numeric IPv4 forms,
before allowlist matching. It passes the approved URL string unchanged to the
injected/production RAOP sender. When the sender calls pyatv's
`receiver.stream.stream_file`, pyatv's RAOP source implementation owns retrieval
of an approved HTTP(S) URL; the helper does not add a downloader or local media
cache. Host allowlisting and loopback rejection remain helper control-plane
guardrails. `airplay2` targets are rejected. `/health` is the only
unauthenticated route and returns only
`{"status":"ok"}`. Stream and job routes require an exact
`Authorization: Bearer <TOKEN>` header and expose only opaque job IDs and job
status.

The CLI reads the token only from the named environment variable
`AIRPLAY_HELPER_BEARER_TOKEN`; it never accepts a token command-line argument.
The default bind is loopback (`127.0.0.1`) and access logging is disabled so
URLs, target identities, and token values are not written by the helper:

```text
set AIRPLAY_HELPER_BEARER_TOKEN=<TOKEN_FROM_SECRET_STORE>
python -m airplay_helper.server ^
  --targets-file <TARGETS_FILE> ^
  --allowed-media-host <APPROVED_MEDIA_HOST> ^
  --port 8765
```

Repeat `--allowed-media-host` for additional exact hostnames. The HTTP service
is deliberately separate from Home Assistant and Music Assistant; native
AirPlay 2 is not implemented. The source tests use aiohttp's local test
utilities and fake senders only; they do not launch this CLI or contact a
device/network.
