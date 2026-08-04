# ha-reolink-talk

A native Home Assistant custom integration that adds **two-way audio ("talk")** to Reolink cameras connected through a **Reolink Home Hub / NVR**, using the reverse-engineered **Baichuan** protocol. No separate server, no extra process — everything runs inside Home Assistant's own HTTP server.

> This is a fork/extension of [joeblack2k/reolink_talk](https://github.com/joeblack2k/reolink_talk) (MIT licensed). The original project's README flags that two-way audio may not be usable when a camera sits behind an NVR/Home Hub — this fork specifically adds multi-channel Home Hub support, plus a live/streaming push-to-talk mode with an inline Lovelace button, on top of the original's one-shot `media_player` playback. See [Credits](#credits) below.

Two ways to talk to your camera:

- **One-shot playback** — send a TTS message or audio file to the camera speaker via a `media_player` entity (`media_player.play_media`), just like any other HA media player.
- **Live push-to-talk** — a microphone button that streams your voice to the camera in near real time, embedded directly on top of your existing camera card in Lovelace (no duplicate video stream, no extra dashboard page).

## Why this exists

Reolink's official two-way audio only works through the Reolink app. There was no clean way to trigger it from Home Assistant — most existing tools either rely on ONVIF (which many Reolink models don't expose talk-back through) or require running [neolink](https://github.com/QuantumEntangledAndy/neolink) as a separate RTSP bridge. This integration talks the Baichuan binary protocol directly from HA, using the same message framing validated against neolink's reference implementation (ADPCM/BcMedia framing confirmed byte-exact).

## Features

- Native `HomeAssistantView`-based HTTP/WebSocket endpoints — registered on HA's own web server, no extra port, no reverse proxy needed.
- IMA/DVI-4 ADPCM audio encoding done in Python, matching the camera's advertised `TalkAbility` (`length_per_encoder`, sample rate) exactly.
- Config-flow based setup (add via **Settings → Devices & Services → Add Integration**).
- A `media_player` entity per camera channel for one-shot TTS/file playback.
- A drop-in Lovelace custom element (`reolink-talk-button`) for live push-to-talk that overlays directly on an already-playing camera card — it opens only an audio WebSocket on tap, reusing whatever video connection your camera card already has open.
- Automatic recovery from a stuck/lingering talk session on the camera (handles Baichuan rejection codes 400/421/422 with an automatic stop-and-retry).
- Client-side cooldown to avoid race conditions on rapid re-tap.

## Requirements

- Home Assistant with the [Reolink](https://www.home-assistant.io/integrations/reolink/) integration already set up for your Home Hub / NVR (this integration reuses that config entry's credentials).
- [`reolink-aio`](https://github.com/starkillerOG/reolink_aio) (pulled in automatically as a dependency of HA's own Reolink integration).
- `ffmpeg` available in your Home Assistant environment (used to decode/transcode audio for the one-shot TTS/file playback path). The official HA Docker/OS images already include it.
- A camera/channel that supports Reolink's two-way talk feature and advertises ADPCM as its talk audio codec (most battery and PoE Reolink cameras with a built-in speaker).
- For the inline Lovelace button: [`advanced-camera-card`](https://github.com/dermotduffy/advanced-camera-card) (not required for the `media_player`/TTS path).

## Installation

**Step 1 — get the files onto your HA instance.**

- **Option A (HACS):** In HACS, add this repository as a custom repository (`https://github.com/mathiasmholm/ha-reolink-talk`, category **Integration**), then install **Reolink Talk (Two-Way Audio + Live Talk)**. This places `custom_components/reolink_talk/` for you — you still need to copy the frontend file manually (next bullet).
- **Option B (manual):** copy `custom_components/reolink_talk/` into your HA `config/custom_components/` directory.
- Either way, also copy `www/reolink-talk-button.js` into your HA `config/www/` directory (it will be served automatically at `/local/reolink-talk-button.js`).

**Step 2 — set your camera details.** Edit `custom_components/reolink_talk/talk_live_view.py` and update:

```python
HOME_HUB_HOST = "10.10.40.8"          # your Home Hub / NVR's IP
CAMERA_CHANNELS = {
    "front_door": 0,
    "entrance": 1,
    "living_room": 2,
}
```

`HOME_HUB_HOST` is your Home Hub/NVR's IP address. Each entry in `CAMERA_CHANNELS` is `"a short key you choose": <channel number>` — the channel number is the camera's position in the Baichuan channel list, typically the same order it appears in the Reolink app. You'll reuse these short keys later in your dashboard YAML.

**Step 3 — restart Home Assistant.**

**Step 4 — add the integration.** Go to **Settings → Devices & Services → Add Integration**, search for **Reolink Talk**, and select the Reolink config entry it should attach to.

**Step 5 — find your media_player entity.** Go to **Settings → Devices & Services → Entities**, search "talk" — note the entity ID (e.g. `media_player.front_door_talk`), you'll need it for one-shot playback below.

**Step 6 — register the Lovelace resource.** **Settings → Dashboards → ⋮ → Resources → Add Resource**, URL `/local/reolink-talk-button.js`, type **JavaScript Module**. Bump the `?v=` query string on the URL any time you update the file, to bust HA/Companion App caching.

That's the full setup — everything below is how to use it.

## Usage

### One-shot playback (TTS / file)

```yaml
service: media_player.play_media
target:
  entity_id: media_player.<your_camera>_talk
data:
  media_content_id: "Someone is at the door"
  media_content_type: music
```

Works with any HA TTS engine via the standard `tts.speak` / `media_player.play_media` flow.

### Live push-to-talk (inline button)

Add the custom element as a picture-element on top of an existing `advanced-camera-card`:

```yaml
type: custom:advanced-camera-card
cameras:
  - camera_entity: camera.your_camera
elements:
  - type: custom:reolink-talk-button
    camera: your_camera_key   # must match a key in CAMERA_CHANNELS (Installation, Step 2)
    style:
      bottom: 10px
      left: 50%
      transform: translateX(-50%)
```

Tap once to start talking, tap again to stop. The button changes color to indicate state (idle / connecting / live / error). The `camera:` value must match one of the keys you set in `CAMERA_CHANNELS` during Step 2 of Installation.

## How it works (protocol notes)

- Talk sessions are negotiated over Baichuan cmd IDs: `10` (query `TalkAbility`), `201` (`TalkConfig`, starts the session), `202` (binary ADPCM audio payload), `11` (stop).
- Audio is encoded as IMA/DVI-4 ADPCM in blocks sized from the camera's advertised `length_per_encoder`, wrapped in Reolink's `BcMedia` binary framing (`bw10` magic, block-size header) before being sent as cmd `202` binary payloads.
- The browser captures mic audio via `getUserMedia` + `AudioContext`, downsamples to 16 kHz mono PCM16, and streams it over a WebSocket to a Home-Assistant-hosted endpoint (`/api/reolink_talk/live_ws`), which encodes each block to ADPCM and forwards it to the camera as it arrives.
- Rejection code `421` (and `400`/`422`) from a `TalkConfig` request means a prior session on that channel wasn't cleanly torn down — the integration automatically sends a stop (`cmd 11`) and retries once.

## Known limitations

- `requires_auth = False` is set on the HTTP views so the WebSocket can be opened from a plain browser connection without HA's bearer-token auth. This is a deliberate tradeoff to keep the live-talk flow simple — be aware these endpoints are reachable by anyone who can reach your HA instance's HTTP port.
- Only tested against a Reolink Home Hub with battery-powered cameras advertising ADPCM talk support; other Reolink NVR/hub models or codecs may need adjustment.
- The `media_player` (one-shot) and live push-to-talk paths currently duplicate some TalkConfig retry logic; a future cleanup could unify them under one code path.

## Credits

- [joeblack2k/reolink_talk](https://github.com/joeblack2k/reolink_talk) — the original project this fork is based on (MIT licensed), which introduced the `media_player`-based one-shot talk/TTS playback and the `TalkAbility`/ADPCM approach for standalone Reolink cameras.
- [neolink](https://github.com/QuantumEntangledAndy/neolink) — reference implementation used to validate the Baichuan/BcMedia framing.
- [reolink_aio](https://github.com/starkillerOG/reolink_aio) — the underlying Baichuan client library, also used by HA's core Reolink integration.
- [advanced-camera-card](https://github.com/dermotduffy/advanced-camera-card) — the Lovelace card this integration overlays its talk button on.

## What's new compared to the original

- Home Hub / NVR multi-channel support (`CAMERA_CHANNELS` mapping), addressing the original project's noted limitation that talk may not work for cameras behind an NVR/Home Hub.
- Live/streaming push-to-talk over a WebSocket, instead of one-shot file/TTS playback only.
- An inline Lovelace custom element (`reolink-talk-button`) that overlays the existing camera card with zero extra video connections.
- Automatic recovery from stuck talk sessions (Baichuan rejection codes 400/421/422) and a client-side cooldown against rapid re-tap races.

## License

MIT (see `LICENSE`) — inherited from the upstream [joeblack2k/reolink_talk](https://github.com/joeblack2k/reolink_talk) project.
