"""Keeps a connection to the adapter and reads the car when its engine is running.

Battery voltage comes from the adapter itself (ATRV) and is read all the time.
OBD queries go to the car only while that voltage says the alternator is
charging: asking a parked car's sleeping CAN bus can wake its modules, and a
parked car has nothing new to say anyway. Everything read from the car is kept
(and stored across restarts), so fuel and odometer show the last known values.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime

from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CONF_POLL_INTERVAL,
    CONF_RUNNING_VOLTAGE,
    CONF_VEHICLE,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_RUNNING_VOLTAGE,
    DOMAIN,
    EXT_TRIES,
    RETRY_MAX,
    RETRY_MIN,
    RUNNING_POLL_INTERVAL,
)
from .elm327 import PIDS, Elm327, Elm327Error, ExtPid, decode_monitor_status
from .vehicles import GENERIC, VEHICLES

_LOGGER = logging.getLogger(__name__)

ERRORS = (BleakError, Elm327Error, TimeoutError, EOFError)


@dataclass
class CarState:
    in_range: bool = False
    connected: bool = False
    voltage: float | None = None
    engine_running: bool = False
    # Last values the car answered with, keyed by Pid.key.
    values: dict[str, float | int] = field(default_factory=dict)
    mil: bool | None = None
    dtcs: list[str] | None = None
    supported: set[int] | None = None
    last_read: datetime | None = None
    adapter: str | None = None


type Elm327ConfigEntry = ConfigEntry[Elm327Coordinator]


class Elm327Coordinator(DataUpdateCoordinator[CarState]):
    """Push-style: the connection loop calls async_set_updated_data itself."""

    def __init__(self, hass: HomeAssistant, entry: Elm327ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, name=entry.title, config_entry=entry)
        self.address: str = entry.data[CONF_ADDRESS]
        self.data = CarState()
        self._store: Store[dict] = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}")
        self._client: BleakClientWithServiceCache | None = None
        self._elm: Elm327 | None = None
        self._wake = asyncio.Event()
        self._read_dtcs = True
        # Unanswered reads per service 22 value this drive. After EXT_TRIES misses a value
        # isn't asked for again until the next drive.
        self._ext_misses: dict[str, int] = {}
        self.device_info = DeviceInfo(
            identifiers={(DOMAIN, self.address)},
            connections={(CONNECTION_BLUETOOTH, self.address)},
            name=entry.title,
            manufacturer="ELM327 Bluetooth LE adapter",
        )

    @property
    def running_voltage(self) -> float:
        return self.config_entry.options.get(CONF_RUNNING_VOLTAGE, DEFAULT_RUNNING_VOLTAGE)

    @property
    def poll_interval(self) -> float:
        return self.config_entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)

    @property
    def extended(self) -> tuple[ExtPid, ...]:
        """The chosen vehicle's manufacturer-specific values."""
        vehicle = self.config_entry.options.get(CONF_VEHICLE, GENERIC)
        return VEHICLES.get(vehicle, VEHICLES[GENERIC])[1]

    async def async_start(self) -> None:
        if stored := await self._store.async_load():
            state = self.data
            state.values = stored.get("values", {})
            state.mil = stored.get("mil")
            state.dtcs = stored.get("dtcs")
            if (supported := stored.get("supported")) is not None:
                state.supported = set(supported)
            if last_read := stored.get("last_read"):
                state.last_read = dt_util.parse_datetime(last_read)
        self.data.in_range = bluetooth.async_address_present(self.hass, self.address, True)

        entry = self.config_entry
        entry.async_on_unload(bluetooth.async_register_callback(
            self.hass, self._on_advertisement,
            bluetooth.BluetoothCallbackMatcher(address=self.address, connectable=True),
            bluetooth.BluetoothScanningMode.ACTIVE,
        ))
        entry.async_on_unload(bluetooth.async_track_unavailable(
            self.hass, self._on_unavailable, self.address, connectable=True))
        entry.async_create_background_task(self.hass, self._run(), f"{DOMAIN} {self.address}")

    async def async_stop(self) -> None:
        await self._disconnect()

    @callback
    def _on_advertisement(self, info: bluetooth.BluetoothServiceInfoBleak,
                          change: bluetooth.BluetoothChange) -> None:
        if not self.data.in_range:
            self.data.in_range = True
            self.async_set_updated_data(self.data)
        if self._elm is None:
            self._wake.set()

    @callback
    def _on_unavailable(self, info: bluetooth.BluetoothServiceInfoBleak) -> None:
        # Many adapters stop advertising while connected, so only a lost
        # connection plus silence means the car has gone.
        if not self.data.connected and self.data.in_range:
            self.data.in_range = False
            self.data.voltage = None
            self.async_set_updated_data(self.data)

    @callback
    def _on_disconnect(self, client: BleakClientWithServiceCache) -> None:
        _LOGGER.debug("%s: disconnected", self.address)
        if client is self._client:
            self._client = self._elm = None
            self._mark_disconnected()
            self._wake.set()

    def _mark_disconnected(self) -> None:
        state = self.data
        state.connected = state.engine_running = False
        state.in_range = bluetooth.async_address_present(self.hass, self.address, True)
        if not state.in_range:
            state.voltage = None
        self.async_set_updated_data(state)

    async def _sleep(self, seconds: float) -> None:
        try:
            async with asyncio.timeout(seconds):
                await self._wake.wait()
        except TimeoutError:
            pass
        self._wake.clear()

    async def _run(self) -> None:
        while True:
            try:
                await self._loop()
            except Exception:
                _LOGGER.exception("%s: unexpected error, retrying in %ss", self.address, RETRY_MAX)
                await self._disconnect()
                await asyncio.sleep(RETRY_MAX)

    async def _loop(self) -> None:
        retry = RETRY_MIN
        while True:
            if self._elm is None:
                device = bluetooth.async_ble_device_from_address(self.hass, self.address, True)
                if device is None:
                    await self._sleep(300)
                    continue
                try:
                    await self._connect(device)
                    retry = RETRY_MIN
                except ERRORS as err:
                    _LOGGER.debug("%s: connect failed: %s", self.address, err)
                    await self._disconnect()
                    await asyncio.sleep(retry)
                    retry = min(retry * 2, RETRY_MAX)
                    continue
            try:
                await self._poll()
            except ERRORS as err:
                _LOGGER.debug("%s: poll failed: %s", self.address, err)
                await self._disconnect()
                continue
            await self._sleep(
                RUNNING_POLL_INTERVAL if self.data.engine_running else self.poll_interval)

    async def _connect(self, device) -> None:
        client = await establish_connection(
            BleakClientWithServiceCache, device, self.config_entry.title,
            disconnected_callback=self._on_disconnect, max_attempts=3,
            ble_device_callback=lambda: bluetooth.async_ble_device_from_address(
                self.hass, self.address, True) or device,
        )
        self._client = client
        elm = Elm327(client)
        adapter = await elm.start()
        self._elm = elm
        state = self.data
        state.connected = state.in_range = True
        if adapter != state.adapter:
            state.adapter = adapter
            dr.async_get(self.hass).async_get_or_create(
                config_entry_id=self.config_entry.entry_id,
                identifiers={(DOMAIN, self.address)}, model=adapter)
        _LOGGER.debug("%s: connected, %s", self.address, adapter)

    async def _disconnect(self) -> None:
        client, self._client, self._elm = self._client, None, None
        if client is not None:
            try:
                await client.disconnect()
            except ERRORS:
                pass
        if self.data.connected:
            self._mark_disconnected()

    async def _poll(self) -> None:
        elm, state = self._elm, self.data
        assert elm is not None
        state.voltage = await elm.voltage()
        was_running = state.engine_running
        state.engine_running = state.voltage >= self.running_voltage
        if state.engine_running:
            if not was_running:
                _LOGGER.debug("%s: engine running at %.1f V", self.address, state.voltage)
                self._read_dtcs = True
                self._ext_misses.clear()
            await self._read_car(elm, state)
        self.async_set_updated_data(state)

    async def _read_car(self, elm: Elm327, state: CarState) -> None:
        if not state.supported:
            state.supported = await elm.supported() or None
            if not state.supported:
                _LOGGER.debug("%s: car didn't answer the supported-PIDs query", self.address)
                return
            _LOGGER.info("%s: car supports PIDs %s", self.address,
                         " ".join(f"{p:02X}" for p in sorted(state.supported)))
        answered = False
        if 0x01 in state.supported and (status := await elm.mode01(0x01)):
            mil, count = decode_monitor_status(status)
            if mil != state.mil or count != len(state.dtcs or ()):
                self._read_dtcs = True
            state.mil = mil
            answered = True
        for pid in PIDS:
            if pid.pid in state.supported and (payload := await elm.mode01(pid.pid)):
                if len(payload) >= pid.size:
                    state.values[pid.key] = pid.decode(payload)
                    answered = True
        if extended := [e for e in self.extended if self._ext_misses.get(e.key, 0) < EXT_TRIES]:
            try:
                for ext in extended:
                    payload = await elm.mode22(ext.header, ext.rx, ext.did)
                    if payload is not None and len(payload) >= ext.size:
                        state.values[ext.key] = ext.decode(payload)
                        self._ext_misses.pop(ext.key, None)
                        answered = True
                    else:
                        misses = self._ext_misses[ext.key] = self._ext_misses.get(ext.key, 0) + 1
                        _LOGGER.debug("%s: no answer for %s (%d of %d)",
                                      self.address, ext.key, misses, EXT_TRIES)
            finally:
                await elm.broadcast()
        if self._read_dtcs and answered:
            state.dtcs = await elm.dtcs()
            self._read_dtcs = False
        if answered:
            state.last_read = dt_util.utcnow()
            await self._store.async_save({
                "values": state.values,
                "mil": state.mil,
                "dtcs": state.dtcs,
                "supported": sorted(state.supported),
                "last_read": state.last_read.isoformat(),
            })
