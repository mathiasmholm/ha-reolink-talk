"""Live (streaming) push-to-talk HTTP/WebSocket views for reolink_talk.

Reuses the already-verified building blocks from talk.py (TalkAbility parsing,
TalkConfig XML variants, the DVI-4 ADPCM encoder, BcMedia framing, and the
low-level send_talk_binary sender) but instead of encoding one pre-built file
and sending it once, it accepts a continuous stream of raw PCM16LE mono audio
over a WebSocket (from a browser microphone) and forwards it to the camera
block-by-block in near real time.

Runs inside Home Assistant's own HTTP server -- no separate process, no
separate reverse-proxy host needed.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aiohttp import WSMsgType, web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .talk import (
    build_talk_config_variants,
    ima_adpcm_encode_dvi_blocks,
    parse_talk_ability,
    send_talk_binary,
    talk_binary_payload,
)

_LOGGER = logging.getLogger(__name__)

HOME_HUB_HOST = "10.10.40.8"
CAMERA_CHANNELS = {"terass": 0, "ingang": 1, "vardagsrum": 2}



def _resolve_home_hub_entry(hass: HomeAssistant):
    entries = hass.config_entries.async_entries("reolink")
    for entry in entries:
        if entry.data.get("host") == HOME_HUB_HOST:
            return entry
    return entries[0] if entries else None


class ReolinkTalkLiveWebSocketView(HomeAssistantView):
    """Accepts a live mic PCM stream and forwards it to the camera as talk audio."""

    url = "/api/reolink_talk/live_ws"
    name = "api:reolink_talk:live_ws"
    requires_auth = False

    async def get(self, request: web.Request):
        hass: HomeAssistant = request.app["hass"]
        ws = web.WebSocketResponse(max_msg_size=0)
        await ws.prepare(request)

        camera = request.query.get("camera", "vardagsrum")
        channel = CAMERA_CHANNELS.get(camera)
        if channel is None:
            await ws.close(code=4000, message=f"unknown camera {camera!r}".encode())
            return ws

        entry = _resolve_home_hub_entry(hass)
        if entry is None:
            await ws.close(code=4001, message=b"no reolink config entry found")
            return ws

        data = entry.data
        _LOGGER.info("Live talk connected: camera=%s channel=%s", camera, channel)

        from reolink_aio.api import Host
        from reolink_aio.baichuan import util as bc_util
        from reolink_aio.exceptions import ApiError

        host = Host(
            host=data["host"],
            username=data["username"],
            password=data["password"],
            port=data.get("port"),
            use_https=data.get("use_https"),
            bc_port=data.get("baichuan_port", 9000),
            aiohttp_get_session_callback=lambda: async_get_clientsession(hass),
        )
        bc = host.baichuan
        enc_used = None
        try:
            await bc.login()
            ability_xml = await bc.send(cmd_id=10, channel=channel)
            ability = parse_talk_ability(ability_xml)
            if ability.audio_type.lower() != "adpcm":
                _LOGGER.error("Camera ch=%s does not support ADPCM talk (got %s)", channel, ability.audio_type)
                await ws.close(code=4002, message=b"camera does not support adpcm talk")
                return ws

            full_block = (int(ability.length_per_encoder) // 2) + 4
            payload_bytes = full_block - 4
            payload_samples = payload_bytes * 2
            samples_per_block = payload_samples + 1  # +1 implied header sample
            bytes_per_block_pcm = samples_per_block * 2  # s16le -> 2 bytes/sample

            _LOGGER.info(
                "TalkAbility ch=%s sampleRate=%s lengthPerEncoder=%s full_block=%s pcm_bytes_per_block=%s",
                channel, ability.sample_rate, ability.length_per_encoder, full_block, bytes_per_block_pcm,
            )

            # Start talk session -- same TalkConfig send/fallback dance as
            # talk_playback() in talk.py, kept local here to avoid touching
            # the already-verified file-playback code path.
            last_err = None
            for cfg_xml in build_talk_config_variants(channel, ability):
                for enc in (bc_util.EncType.AES, bc_util.EncType.BC):
                    try:
                        await bc.send(cmd_id=201, channel=channel, body=cfg_xml, enc_type=enc)
                        enc_used = enc
                        last_err = None
                        break
                    except ApiError as err:
                        last_err = err
                        rsp = getattr(err, "rspCode", None)
                        if rsp in (400, 421, 422):
                            try:
                                await bc.send(cmd_id=11, channel=channel, enc_type=enc)
                                await asyncio.sleep(0.1)
                                await bc.send(cmd_id=201, channel=channel, body=cfg_xml, enc_type=enc)
                                enc_used = enc
                                last_err = None
                                break
                            except Exception:
                                pass
                        continue
                if enc_used is not None:
                    break

            if enc_used is None:
                _LOGGER.error("Live talk: TalkConfig rejected for ch=%s (%s)", channel, last_err)
                await ws.close(code=4003, message=b"camera rejected talk config")
                return ws

            _LOGGER.info("Live talk session started: camera=%s channel=%s enc=%s", camera, channel, enc_used.value)
            await ws.send_json({"status": "ready", "sampleRate": ability.sample_rate})

            pcm_buffer = bytearray()
            async for msg in ws:
                if msg.type == WSMsgType.BINARY:
                    pcm_buffer += msg.data
                    while len(pcm_buffer) >= bytes_per_block_pcm:
                        chunk = bytes(pcm_buffer[:bytes_per_block_pcm])
                        del pcm_buffer[:bytes_per_block_pcm]
                        adpcm_block = ima_adpcm_encode_dvi_blocks(chunk, full_block_size=full_block)
                        if not adpcm_block:
                            continue
                        for payload, _n in talk_binary_payload(adpcm_block, full_block, blocks_per_payload=1):
                            await send_talk_binary(bc, channel, payload, enc_type=enc_used)
                elif msg.type == WSMsgType.ERROR:
                    _LOGGER.warning("Live talk WS error: %s", ws.exception())
                    break
                # TEXT control messages are ignored; the browser closing the
                # socket is what ends the loop.

            _LOGGER.info("Live talk disconnected: camera=%s channel=%s", camera, channel)
        except Exception:
            _LOGGER.exception("Live talk relay error (camera=%s)", camera)
        finally:
            if enc_used is not None:
                try:
                    await bc.send(cmd_id=11, channel=channel, enc_type=enc_used)
                except Exception as e:
                    _LOGGER.warning("cmd11 stop failed (ignored): %s", e)
            try:
                await host.logout()
            except Exception:
                pass

        return ws


def async_register_views(hass: HomeAssistant) -> None:
    """Register the live-talk views exactly once."""
    key = "reolink_talk_live_views_registered"
    if hass.data.get(key):
        return
    hass.data[key] = True
    hass.http.register_view(ReolinkTalkLiveWebSocketView())
    _LOGGER.info("Registered reolink_talk live-talk WebSocket view at /api/reolink_talk/live_ws")
