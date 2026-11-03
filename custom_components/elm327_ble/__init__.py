"""OBD-II from an ELM327 Bluetooth LE adapter, through HA's Bluetooth (proxies included)."""

from __future__ import annotations

import logging

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_SIGNALS, CONF_VEHICLE, CONF_YEAR, PLATFORMS
from .coordinator import Elm327ConfigEntry, Elm327Coordinator
from .obdb import GENERIC, download, select

_LOGGER = logging.getLogger(__name__)

# Vehicle options from before OBDb signal sets were read directly (1.1.0).
LEGACY_VEHICLES = {"mazda_cx9_tc": "Mazda-CX-9"}


async def async_setup_entry(hass: HomeAssistant, entry: Elm327ConfigEntry) -> bool:
    await _async_fetch_signals(hass, entry)
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



async def _async_fetch_signals(hass: HomeAssistant, entry: Elm327ConfigEntry) -> None:
    """Fill in the saved commands for a car chosen without them (a 1.1.0 vehicle).

    The options flow normally saves them. If GitHub can't be reached, the entry runs
    on standard OBD-II and tries again at the next start.
    """
    vehicle = entry.options.get(CONF_VEHICLE, GENERIC)
    if vehicle == GENERIC or CONF_SIGNALS in entry.options:
        return
    repo = LEGACY_VEHICLES.get(vehicle, vehicle)
    try:
        signalset = await download(async_get_clientsession(hass), repo)
    except (aiohttp.ClientError, TimeoutError, ValueError) as err:
        _LOGGER.warning("Couldn't download the OBDb signal set for %s, will retry at the next "
                        "start: %s", repo, err)
        return
    hass.config_entries.async_update_entry(entry, options={
        **entry.options, CONF_VEHICLE: repo,
        CONF_SIGNALS: select(signalset, entry.options.get(CONF_YEAR)),
    })
