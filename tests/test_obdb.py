"""Tests for reading OBDb signal sets.

The commands and recorded replies below are excerpts from OBDb
(https://github.com/OBDb: Mazda-CX-9, Toyota-RAV4, Hyundai-Elantra), CC BY-SA 4.0.
"""

import pytest
from conftest import load

obdb = load("obdb")


def _tp(did, sid, name, metric):
    return {"hdr": "720", "rax": "728", "cmd": {"22": did}, "freq": 1, "signals": [
        {"id": sid, "path": "Tires", "name": name, "suggestedMetric": metric,
         "fmt": {"len": 8, "max": 3.5, "mul": 1373, "div": 100000, "unit": "bars"}}]}


CX9 = {"commands": [
    _tp("2A05", "CX9_TP_1", "Rear right tire pressure", "rearRightTirePressure"),
    _tp("2A07", "CX9_TP_3", "Front left tire pressure", "frontLeftTirePressure"),
    {"hdr": "720", "rax": "728", "cmd": {"22": "2A0A"}, "freq": 15, "signals": [
        {"id": "CX9_TT_1", "path": "Tires", "name": "Rear right tire temperature",
         "suggestedMetric": "rearRightTireTemperature",
         "fmt": {"len": 8, "max": 205, "min": -50, "add": -50, "unit": "celsius"}}]},
    {"hdr": "720", "rax": "728", "cmd": {"22": "61B1"}, "freq": 1, "signals": [
        {"id": "CX9_FLV", "path": "Fuel", "name": "Fuel level", "suggestedMetric": "fuelTankLevel",
         "fmt": {"len": 8, "max": 255, "unit": "liters"}}]},
    # No suggestedMetric: a diagnostic value, not one of the everyday readings.
    {"hdr": "7E0", "rax": "7E8", "cmd": {"22": "0415"}, "freq": 1, "signals": [
        {"id": "CX9_EOP", "path": "Engine", "name": "Engine oil pressure",
         "fmt": {"len": 16, "max": 32767, "min": -32768, "sign": True, "unit": "kilopascal"}}]},
    {"hdr": "7E0", "rax": "7E8", "cmd": {"22": "1310"}, "freq": 1, "signals": [
        {"id": "CX9_EOT", "path": "Engine", "name": "Engine oil temperature",
         "suggestedMetric": "engineOilTemperature",
         "fmt": {"len": 16, "max": 615.35, "min": -40, "div": 100, "add": -40,
                 "unit": "celsius"}}]},
    {"hdr": "7E1", "rax": "7E9", "cmd": {"22": "1E1C"}, "freq": 1, "signals": [
        {"id": "CX9_TRANS_T", "path": "Transmission", "name": "Transmission temperature",
         "suggestedMetric": "transmissionFluidTemperature",
         "fmt": {"len": 16, "max": 500, "min": -500, "div": 16, "sign": True,
                 "unit": "celsius"}}]},
]}

# One command, four readings at different bit offsets, for model years up to 2018.
RAV4_TYRES = {"hdr": "750", "rax": "758", "cmd": {"21": "30"}, "freq": 1, "fcm1": True,
              "filter": {"to": 2018}, "signals": [
                  {"id": f"RAV4_TP_{i}", "name": f"{w} tire pressure",
                   "suggestedMetric": f"{w}TirePressure",
                   "fmt": {"bix": 8 * i, "len": 8, "max": 3.8, "div": 58, "add": -0.5,
                           "nullmin": 0, "unit": "bars"}}
                  for i, w in enumerate(("frontLeft", "frontRight", "rearLeft", "rearRight"))]}


def _metric(name, metric, fmt, **command):
    return {"hdr": "7E0", "cmd": {"22": "F42F"}, "freq": 1, **command, "signals": [
        {"id": name, "name": name, "suggestedMetric": metric, "fmt": fmt}]}


def test_cx9_selects_the_readings_1_1_0_had():
    selected = obdb.select(CX9, None)
    assert [(c["hdr"], c["rax"], c["svc"], c["pid"]) for c in selected] == [
        ("720", "728", "22", "2A05"), ("720", "728", "22", "2A07"), ("720", "728", "22", "2A0A"),
        ("720", "728", "22", "61B1"), ("7E0", "7E8", "22", "1310"), ("7E1", "7E9", "22", "1E1C")]
    assert obdb.keys(selected) == {
        "tyre_pressure_rear_right", "tyre_pressure_front_left", "tyre_temperature_rear_right",
        "fuel_remaining", "oil_temperature", "transmission_temperature"}
    assert not obdb.uses_years(CX9)


def test_cx9_values_match_obdb_recordings():
    by_pid = {c.pid: c for c in obdb.commands(obdb.select(CX9, None))}
    # 72804622A05E1 -> 3.08925 bar
    assert by_pid[0x2A05].values(bytes.fromhex("E1")) == {"tyre_pressure_rear_right": 308.92}
    # 728046261B125 -> 37 L
    assert by_pid[0x61B1].values(bytes.fromhex("25")) == {"fuel_remaining": 37}
    # 7E905621E1C0026 -> 2.375 °C, and a negative one
    assert by_pid[0x1E1C].values(bytes.fromhex("0026")) == {"transmission_temperature": 2.38}
    assert by_pid[0x1E1C].values(bytes.fromhex("FFF0")) == {"transmission_temperature": -1}
    assert by_pid[0x1310].values(bytes.fromhex("3A98")) == {"oil_temperature": 110}
    assert by_pid[0x2A0A].values(bytes.fromhex("46")) == {"tyre_temperature_rear_right": 20}


def test_commands_addresses():
    cmds = obdb.commands(obdb.select({"commands": [
        CX9["commands"][0], RAV4_TYRES,
        _metric("NO_RAX", "odometer", {"len": 24, "max": 16777215, "unit": "kilometers"}),
        _metric("BROADCAST", "odometer", {"len": 24, "max": 16777215, "unit": "kilometers"},
                hdr="7DF"),
    ]}, None))
    assert [(c.header, c.rx, c.service, c.pid, c.pid_bytes, c.flow_control) for c in cmds] == [
        (0x720, 0x728, 0x22, 0x2A05, 2, False), (0x750, 0x758, 0x21, 0x30, 1, True),
        (0x7E0, 0x7E8, 0x22, 0xF42F, 2, False), (0x7DF, None, 0x22, 0xF42F, 2, False)]
    assert cmds[0].name == "720 222A05"
    assert cmds[1].name == "750 2130"


def test_signals_by_bit_offset_with_nulls():
    (cmd,) = obdb.commands(obdb.select({"commands": [RAV4_TYRES]}, 2016))
    # 0 is OBDb's "no sensor" (nullmin) for this module.
    assert cmd.values(bytes([145, 146, 0, 144])) == {
        "tyre_pressure_front_left": 200, "tyre_pressure_front_right": 201.72,
        "tyre_pressure_rear_right": 198.28}
    assert cmd.values(bytes([145])) == {"tyre_pressure_front_left": 200}


def test_model_year_filters():
    signalset = {"commands": [RAV4_TYRES, {**RAV4_TYRES, "filter": {"years": [2020]}},
                              {**RAV4_TYRES, "filter": {"from": 2022}}]}
    assert obdb.uses_years(signalset)
    count = {year: len(obdb.select(signalset, year))
             for year in (None, 2016, 2018, 2019, 2020, 2021, 2023)}
    assert count == {None: 3, 2016: 1, 2018: 1, 2019: 0, 2020: 1, 2021: 0, 2023: 1}


def test_unusable_commands_and_signals_are_left_out():
    odo = {"len": 24, "max": 16777215, "unit": "kilometers"}
    signalset = {"commands": [
        _metric("EXT_ADDR", "odometer", odo, eax="2A"),
        _metric("SESSION", "odometer", odo, din="03"),
        _metric("29BIT", "odometer", odo, hdr="DA18"),
        _metric("SVC01", "odometer", odo, cmd={"01": "A6"}),
        _metric("LSB", "odometer", {**odo, "blsb": True}),
        _metric("ENUM", "odometer", {"len": 8, "map": {"0": {"value": "OFF"}}}),
        _metric("METRES", "odometer", {**odo, "unit": "meters"}),
        _metric("SPEED", "speed", {"len": 8, "max": 255, "unit": "kilometersPerHour"}),
        _metric("FUEL_UNKNOWN", "fuelTankLevel", {"len": 8, "max": 255, "unit": "scalar"}),
    ]}
    assert obdb.select(signalset, None) == []


@pytest.mark.parametrize(("fmt", "payload", "expected"), [
    ({"len": 8, "max": 255, "unit": "percent"}, "80", 128),
    ({"len": 16, "max": 65535, "unit": "percent"}, "0102", 258),
    ({"bix": 4, "len": 8, "max": 255, "unit": "percent"}, "0FF0", 255),
    ({"len": 8, "max": 127, "min": -128, "sign": True, "unit": "celsius"}, "FF", -1),
    # OBDb's minimum is 0 unless given, so this reads as no value.
    ({"len": 8, "max": 215, "add": -40, "unit": "celsius"}, "00", None),
    ({"len": 8, "max": 100, "unit": "percent"}, "FF", None),
    ({"len": 8, "max": 255, "nullmax": 255, "unit": "percent"}, "FF", None),
    ({"len": 24, "max": 16777215, "unit": "kilometers"}, "0102", None),
])
def test_decode(fmt, payload, expected):
    assert obdb.decode(fmt, bytes.fromhex(payload)) == expected


def test_units_are_converted():
    cases = [("frontLeftTirePressure", "psi", 32, 220.63),
             ("frontLeftTirePressure", "kilopascal", 220, 220),
             ("engineOilTemperature", "fahrenheit", 212, 100),
             ("odometer", "miles", 100, 160.93),
             ("fuelTankLevel", "gallons", 10, 37.85)]
    for metric, unit, raw, expected in cases:
        (cmd,) = obdb.commands(obdb.select({"commands": [
            _metric("X", metric, {"len": 8, "max": 255, "unit": unit})]}, None))
        assert cmd.values(bytes([raw])) == {cmd.signals[0]["key"]: expected}


def test_fuel_unit_picks_the_sensor():
    percent = _metric("FLI", "fuelTankLevel", {"len": 8, "max": 100, "unit": "percent"})
    litres = _metric("FLV", "fuelTankLevel", {"len": 8, "max": 255, "unit": "liters"})
    assert obdb.keys(obdb.select({"commands": [percent, litres]}, None)) == {
        "fuel_level", "fuel_remaining"}


def test_label():
    assert obdb.label("Mazda-CX-9") == "Mazda CX-9"
    assert obdb.label("Hyundai-Kona-Electric") == "Hyundai Kona-Electric"
