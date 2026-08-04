from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_CHANNEL, CONF_REOLINK_ENTRY_IDS, DEFAULT_CHANNEL, DOMAIN
from .talk_live_view import async_register_views

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[str] = ["media_player"]

OLD_WEBRTC_ENTITY_IDS: tuple[str, ...] = (
    "media_player.reolink_poortdeur_low_webrtc_old",
    "media_player.reolink_achtertuin_low_webrtc_old",
    "media_player.reolink_deurbel_webrtc_old",
)


async def async_setup(_hass: HomeAssistant, _config: dict) -> bool:
    return True


def _remove_old_webrtc_entities(hass: HomeAssistant) -> int:
    """Remove legacy WebRTC YAML media_player entities from the entity registry."""
    from homeassistant.helpers import entity_registry as er

    reg = er.async_get(hass)
    removed = 0
    for eid in OLD_WEBRTC_ENTITY_IDS:
        if reg.async_get(eid) is None:
            continue
        reg.async_remove(eid)
        removed += 1
    return removed


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    # Provide a one-shot cleanup service so the user can always remove the legacy
    # YAML/webrtc entities without editing storage files.
    if not hass.services.has_service(DOMAIN, "cleanup_old_webrtc_entities"):

        async def _svc_cleanup(_call) -> None:
            removed = _remove_old_webrtc_entities(hass)
            _LOGGER.info("cleanup_old_webrtc_entities removed %s entities", removed)

        hass.services.async_register(DOMAIN, "cleanup_old_webrtc_entities", _svc_cleanup)

    # Default options: all current Reolink config entries, channel 0.
    if not entry.options:
        reolink_entry_ids = [e.entry_id for e in hass.config_entries.async_entries("reolink")]
        hass.config_entries.async_update_entry(
            entry,
            options={
                CONF_REOLINK_ENTRY_IDS: reolink_entry_ids,
                CONF_CHANNEL: DEFAULT_CHANNEL,
            },
        )

    # Best-effort: remove legacy entities at startup so they don't re-appear in UI.
    removed = _remove_old_webrtc_entities(hass)
    if removed:
        _LOGGER.info("Removed %s legacy webrtc media_player entities", removed)

    async_register_views(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
