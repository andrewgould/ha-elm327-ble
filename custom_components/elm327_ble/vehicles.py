"""Manufacturer-specific values for cars that offer more than standard OBD-II.

Commands and scaling come from the OBDb signal sets (https://github.com/OBDb),
which Pelican and Sidecar also use, licensed CC BY-SA 4.0.
"""

from __future__ import annotations

from .elm327 import ExtPid

GENERIC = "generic"


def _kpa(d: bytes) -> float:
    # OBDb: raw * 1373 / 100000 bar
    return round(d[0] * 1.373, 1)


def _tyres(kind: str, first_did: int, decode) -> tuple[ExtPid, ...]:
    # The TPMS module numbers the wheels rear right, front right, front left, rear left.
    wheels = ("rear_right", "front_right", "front_left", "rear_left")
    return tuple(ExtPid(f"tyre_{kind}_{wheel}", 0x720, 0x728, first_did + i, 1, decode)
                 for i, wheel in enumerate(wheels))


MAZDA_CX9_TC: tuple[ExtPid, ...] = (
    *_tyres("pressure", 0x2A05, _kpa),
    *_tyres("temperature", 0x2A0A, lambda d: d[0] - 50),
    ExtPid("fuel_remaining", 0x720, 0x728, 0x61B1, 1, lambda d: d[0]),
    ExtPid("oil_temperature", 0x7E0, 0x7E8, 0x1310, 2,
           lambda d: round(int.from_bytes(d[:2], "big") / 100 - 40, 1)),
    ExtPid("transmission_temperature", 0x7E1, 0x7E9, 0x1E1C, 2,
           lambda d: round(int.from_bytes(d[:2], "big", signed=True) / 16, 1)),
)

# Option value -> (label, extra values). Labels show in the options form.
VEHICLES: dict[str, tuple[str, tuple[ExtPid, ...]]] = {
    GENERIC: ("Any car: standard OBD-II only", ()),
    "mazda_cx9_tc": ("Mazda CX-9, second generation (2016-2024)", MAZDA_CX9_TC),
}
