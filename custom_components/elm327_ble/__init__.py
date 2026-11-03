"""OBD-II from an ELM327 Bluetooth LE adapter, through HA's Bluetooth (proxies included)."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from .const import PLATFORMS
from .coordinator import Elm327ConfigEntry, Elm327Coordinator


async def async_setup_entry(hass: HomeAssistant, entry: Elm327ConfigEntry) -> bool:
    coordinator = Elm327Coordinator(hass, entry)
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await coordinator.async_start()
    # The vehicle option decides which sensors exist, so options changes reload.
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: Elm327ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: Elm327ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    await entry.runtime_data.async_stop()
    return unloaded

