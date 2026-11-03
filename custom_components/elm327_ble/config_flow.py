"""Config flow: pick the adapter from what Home Assistant's Bluetooth can hear."""

from __future__ import annotations

from typing import Any

import aiohttp
import voluptuous as vol
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_POLL_INTERVAL,
    CONF_RUNNING_VOLTAGE,
    CONF_SIGNALS,
    CONF_VEHICLE,
    CONF_YEAR,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_RUNNING_VOLTAGE,
    DOMAIN,
)
from .coordinator import ERRORS
from .elm327 import KNOWN_SERVICES, Elm327
from .obdb import GENERIC, download, label, select, uses_years
from .vehicles import VEHICLES

NAME_HINTS = ("OBD", "VEEPEAK", "VLINK", "ELM", "OBDLINK", "LELINK")


def _looks_like_adapter(info: bluetooth.BluetoothServiceInfoBleak) -> bool:
    name = (info.name or "").upper()
    return bool(KNOWN_SERVICES & set(info.service_uuids)) or any(h in name for h in NAME_HINTS)


async def _probe(hass, address: str) -> str:
    """Connect and reset the adapter, proving it's an ELM327. Returns its version."""
    device = bluetooth.async_ble_device_from_address(hass, address, True)
    if device is None:
        raise TimeoutError("not in range")
    client = await establish_connection(BleakClientWithServiceCache, device, address,
                                        max_attempts=3)
    try:
        return await Elm327(client).start()
    finally:
        await client.disconnect()


class Elm327ConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            address = user_input[CONF_ADDRESS].upper()
            await self.async_set_unique_id(address)
            self._abort_if_unique_id_configured()
            try:
                version = await _probe(self.hass, address)
            except ERRORS:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=user_input[CONF_NAME], data={CONF_ADDRESS: address},
                    description_placeholders={"version": version})

        current = self._async_current_ids()
        options = [
            selector.SelectOptionDict(
                value=info.address,
                label=(f"{info.name} ({info.address}, {info.rssi} dBm)"
                       if info.name and info.name != info.address
                       else f"{info.address} ({info.rssi} dBm)"))
            for info in bluetooth.async_discovered_service_info(self.hass, connectable=True)
            if info.address not in current and _looks_like_adapter(info)
        ]
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_ADDRESS): selector.SelectSelector(selector.SelectSelectorConfig(
                    options=options, custom_value=True, mode=selector.SelectSelectorMode.DROPDOWN)),
                vol.Required(CONF_NAME, default="Car"): str,
            }),
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry) -> OptionsFlow:
        return Elm327OptionsFlow()


class Elm327OptionsFlow(OptionsFlow):
    """Settings, and the car whose OBDb signal set supplies the extra readings.

    The signal set is downloaded here and the commands it yields are saved with
    the options, so a restart never depends on GitHub.
    """

    def __init__(self) -> None:
        self._options: dict[str, Any] = {}
        self._signalset: dict[str, Any] = {}

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            # A typed name may use the label's spacing: "Mazda CX-9" -> "Mazda-CX-9".
            vehicle = user_input[CONF_VEHICLE].strip().replace(" ", "-")
            self._options = {**user_input, CONF_VEHICLE: vehicle}
            if vehicle == GENERIC:
                return self.async_create_entry(data={**self._options, CONF_SIGNALS: []})
            try:
                self._signalset = await download(async_get_clientsession(self.hass), vehicle)
            except (aiohttp.ClientError, TimeoutError, ValueError):
                errors[CONF_VEHICLE] = "download_failed"
            else:
                if not select(self._signalset, None):
                    errors[CONF_VEHICLE] = "no_readings"
                elif uses_years(self._signalset):
                    return await self.async_step_year()
                else:
                    return self._save(None)

        options = {**self.config_entry.options, **(user_input or {})}
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(CONF_VEHICLE, default=options.get(CONF_VEHICLE, GENERIC)):
                    selector.SelectSelector(selector.SelectSelectorConfig(
                        options=[selector.SelectOptionDict(value=GENERIC, label="None")] + [
                            selector.SelectOptionDict(value=repo, label=label(repo))
                            for repo in VEHICLES],
                        custom_value=True, mode=selector.SelectSelectorMode.DROPDOWN)),
                vol.Required(CONF_RUNNING_VOLTAGE,
                             default=options.get(CONF_RUNNING_VOLTAGE, DEFAULT_RUNNING_VOLTAGE)):
                    vol.All(vol.Coerce(float), vol.Range(min=12.5, max=15)),
                vol.Required(CONF_POLL_INTERVAL,
                             default=options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)):
                    vol.All(vol.Coerce(int), vol.Range(min=5, max=600)),
            }),
            errors=errors,
        )

    async def async_step_year(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Some cars' readings differ between model years."""
        if user_input is not None:
            return self._save(int(user_input[CONF_YEAR]))
        return self.async_show_form(
            step_id="year",
            data_schema=vol.Schema({
                vol.Required(CONF_YEAR, default=self.config_entry.options.get(CONF_YEAR, 2020)):
                    selector.NumberSelector(selector.NumberSelectorConfig(
                        min=1996, max=2035, step=1, mode=selector.NumberSelectorMode.BOX)),
            }),
            description_placeholders={"vehicle": label(self._options[CONF_VEHICLE])},
        )

    def _save(self, year: int | None) -> ConfigFlowResult:
        data = {**self._options, CONF_SIGNALS: select(self._signalset, year)}
        if year is not None:
            data[CONF_YEAR] = year
        return self.async_create_entry(data=data)
