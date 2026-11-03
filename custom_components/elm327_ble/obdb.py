"""Manufacturer-specific readings from OBDb signal sets.

OBDb (https://github.com/OBDb) is the open vehicle signal database behind the
Pelican and Sidecar apps, licensed CC BY-SA 4.0. Each car has a repository whose
signalsets/v3/default.json lists commands (a module address, a service 21 or 22
request) and the signals packed into each reply. A signal OBDb tags with a
`suggestedMetric` is one of the everyday readings (tyres, fuel, odometer ...);
only those become sensors here, mapped onto this integration's own sensor keys
and converted to one unit per key.

Nothing in here imports Home Assistant, so it can be tested on its own.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

GENERIC = "generic"
URL = "https://raw.githubusercontent.com/OBDb/{}/main/signalsets/v3/default.json"
SOURCE = "https://github.com/OBDb/{}"

_WHEELS = {"frontLeft": "front_left", "frontRight": "front_right",
           "rearLeft": "rear_left", "rearRight": "rear_right"}

# suggestedMetric -> sensor key, or {unit: key} where the unit decides (fuel % vs litres).
METRICS: dict[str, str | dict[str, str]] = {
    **{f"{w}TirePressure": f"tyre_pressure_{k}" for w, k in _WHEELS.items()},
    **{f"{w}TireTemperature": f"tyre_temperature_{k}" for w, k in _WHEELS.items()},
    "fuelTankLevel": {"percent": "fuel_level", "liters": "fuel_remaining",
                      "gallons": "fuel_remaining"},
    "odometer": "odometer",
    "engineCoolantTemperature": "coolant_temperature",
    "engineOilTemperature": "oil_temperature",
    "transmissionFluidTemperature": "transmission_temperature",
    "fuelRange": "fuel_range",
    "electricRange": "electric_range",
    "distanceToService": "distance_to_service",
    "stateOfCharge": "state_of_charge",
    "stateOfHealth": "state_of_health",
}

# OBDb unit -> function to this integration's unit for that kind of value
# (kPa, °C, km, L, %). A signal in any other unit is left out.
UNITS: dict[str, Callable[[float], float]] = {
    "kilopascal": lambda v: v,
    "bars": lambda v: v * 100,
    "psi": lambda v: v * 6.894757,
    "celsius": lambda v: v,
    "fahrenheit": lambda v: (v - 32) * 5 / 9,
    "kelvin": lambda v: v - 273.15,
    "kilometers": lambda v: v,
    "miles": lambda v: v * 1.609344,
    "liters": lambda v: v,
    "gallons": lambda v: v * 3.785411,
    "percent": lambda v: v,
}

# Command fields this integration can honour. A command using anything else (29-bit
# or K-line modules, extended addressing, diagnostic sessions, other timeouts) is
# left out rather than sent half-right.
_COMMAND_KEYS = {"hdr", "rax", "cmd", "freq", "fcm1", "signals", "filter", "dbgfilter", "dbg"}
_SERVICES = {"21": 1, "22": 2}  # service -> bytes of PID/DID
_FMT_KEYS = {"bix", "len", "sign", "mul", "div", "add", "min", "max", "nullmin", "nullmax",
             "unit"}


def label(repo: str) -> str:
    """'Mazda-CX-9' -> 'Mazda CX-9': the first hyphen separates the make."""
    return repo.replace("-", " ", 1)


def _key(signal: dict[str, Any]) -> str | None:
    target = METRICS.get(signal.get("suggestedMetric", ""))
    if isinstance(target, dict):
        target = target.get(signal["fmt"].get("unit", ""))
    return target


def _usable(signal: dict[str, Any]) -> bool:
    fmt = signal["fmt"]
    return (fmt.get("unit") in UNITS and "len" in fmt and fmt["len"] <= 64
            and set(fmt) <= _FMT_KEYS | {"omin", "omax", "oval"})


def _in_years(filt: dict[str, Any] | None, year: int | None) -> bool:
    """OBDb filters are a union: up to `to`, from `from`, or one of `years`."""
    if not filt or year is None:
        return True
    return (("to" in filt and year <= filt["to"]) or ("from" in filt and year >= filt["from"])
            or year in filt.get("years", ()))


def uses_years(signalset: dict[str, Any]) -> bool:
    """Whether some of the readings depend on the model year."""
    return any(c.get("filter") for c in select(signalset, None))


def select(signalset: dict[str, Any], year: int | None) -> list[dict[str, Any]]:
    """The commands worth sending for these readings, as small JSON-safe dicts.

    Each is {"hdr", "rax", "svc", "pid", "fcm1", "filter", "signals": [{"key", fmt...}]}.
    Without a year, commands for every model year are kept; where two answer for
    the same reading, the first one that answers wins.
    """
    selected = []
    for command in signalset.get("commands", ()):
        if not set(command) <= _COMMAND_KEYS or len(command.get("hdr", "")) != 3:
            continue
        if len(command["cmd"]) != 1 or not _in_years(command.get("filter"), year):
            continue
        ((svc, pid),) = command["cmd"].items()
        if svc not in _SERVICES or len(pid) != _SERVICES[svc] * 2:
            continue
        signals = [
            {"key": key, **{k: v for k, v in s["fmt"].items() if k in _FMT_KEYS}}
            for s in command["signals"] if (key := _key(s)) and _usable(s)
        ]
        if signals:
            selected.append({
                "hdr": command["hdr"].upper(),
                "rax": command.get("rax", "").upper() or None,
                "svc": svc, "pid": pid.upper(), "fcm1": command.get("fcm1", False),
                "filter": command.get("filter"), "signals": signals,
            })
    return selected


def decode(fmt: dict[str, Any], payload: bytes) -> float | None:
    """One signal from the data bytes after the service and PID echo, in OBDb's unit.

    None when the reply is too short or the value is outside OBDb's valid range.
    """
    bix, length = fmt.get("bix", 0), fmt["len"]
    total = len(payload) * 8
    if bix + length > total:
        return None
    raw = int.from_bytes(payload, "big") >> (total - bix - length) & ((1 << length) - 1)
    if fmt.get("sign") and raw >> (length - 1):
        raw -= 1 << length
    value = raw * fmt.get("mul", 1) / fmt.get("div", 1) + fmt.get("add", 0)
    if ("nullmin" in fmt and value <= fmt["nullmin"]) or (
            "nullmax" in fmt and value >= fmt["nullmax"]):
        return None
    # OBDb's minimum defaults to 0. Out of range is treated as no reading, where
    # OBDb's own tools clamp: a pinned 0 or maximum would read as a real value.
    if value < fmt.get("min", 0) or value > fmt.get("max", value):
        return None
    return value


def convert(fmt: dict[str, Any], value: float) -> float:
    """OBDb's unit to this integration's (kPa, °C, km, L, %), rounded for display."""
    return round(UNITS[fmt["unit"]](value), 2)


@dataclass(frozen=True)
class Command:
    """One request to one module, carrying one or more readings."""

    header: int
    # Address the module answers from; None to accept any (functional requests).
    rx: int | None
    service: int
    pid: int
    pid_bytes: int
    # Multi-frame replies need flow control sent to `header` (ATFCSH + ATFCSM1).
    flow_control: bool
    signals: tuple[dict[str, Any], ...]

    @property
    def keys(self) -> frozenset[str]:
        return frozenset(s["key"] for s in self.signals)

    @property
    def name(self) -> str:
        return f"{self.header:03X} {self.service:02X}{self.pid:0{self.pid_bytes * 2}X}"

    def values(self, payload: bytes) -> dict[str, float]:
        """Sensor key -> converted value for each signal the payload holds."""
        found = {}
        for fmt in self.signals:
            if fmt["key"] not in found and (value := decode(fmt, payload)) is not None:
                found[fmt["key"]] = convert(fmt, value)
        return found


def commands(selected: list[dict[str, Any]]) -> tuple[Command, ...]:
    """Commands from select()'s stored output."""
    out = []
    for c in selected:
        header = int(c["hdr"], 16)
        rx = int(c["rax"], 16) if c["rax"] else (None if header == 0x7DF else header + 8)
        out.append(Command(header, rx, int(c["svc"], 16), int(c["pid"], 16),
                           _SERVICES[c["svc"]], c.get("fcm1", False), tuple(c["signals"])))
    return tuple(out)


def keys(selected: list[dict[str, Any]]) -> set[str]:
    return {s["key"] for c in selected for s in c["signals"]}


async def download(session: Any, repo: str) -> dict[str, Any]:
    """Fetch a car's signal set with an aiohttp session. Raises on failure."""
    async with asyncio.timeout(30), session.get(URL.format(repo)) as response:
        response.raise_for_status()
        return await response.json(content_type=None)
