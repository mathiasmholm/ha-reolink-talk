from __future__ import annotations

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_CHANNEL, CONF_REOLINK_ENTRY_IDS, DEFAULT_CHANNEL, DOMAIN
from .talk_live_view import async_register_views

PLATFORMS: list[str] = ["media_player"]

FRONTEND_URL = "/reolink_talk/reolink-talk-button.js"
FRONTEND_FILE = "frontend/reolink-talk-button.js"


async def _async_register_frontend(hass: HomeAssistant) -> None:
    """Serve the Lovelace element from the integration itself.

    Registered once per HA start, so multiple config entries don't try to
    claim the same static path.
    """
    if hass.data.setdefault(DOMAIN, {}).get("frontend_registered"):
        return

    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                FRONTEND_URL,
                hass.config.path(f"custom_components/{DOMAIN}/{FRONTEND_FILE}"),
                True,
            )
        ]
    )
    add_extra_js_url(hass, FRONTEND_URL)
    hass.data[DOMAIN]["frontend_registered"] = True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
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
    else:
        reolink_entry_ids = entry.options.get(CONF_REOLINK_ENTRY_IDS) or [
            e.entry_id for e in hass.config_entries.async_entries("reolink")
        ]

    # Let talk_live_view discover cameras/channels from these same Reolink
    # entries (instead of a hardcoded host/channel map that would need
    # per-user source edits and get clobbered on every HACS update).
    hass.data.setdefault(DOMAIN, {})["reolink_entry_ids"] = reolink_entry_ids

    await _async_register_frontend(hass)
    async_register_views(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
