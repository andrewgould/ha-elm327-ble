"""Parsing tests for the ELM327 protocol module."""

import asyncio

from conftest import load

elm327 = load("elm327")

PIDS = {p.key: p for p in elm327.PIDS}


def test_voltage_as_the_veepeak_sends_it():
    assert elm327.parse_voltage(b"ATRV\r12.5V\r\r>") == 12.5
    assert elm327.parse_voltage(b"14.1V\r\r>") == 14.1


def test_mode01_with_and_without_spaces():
    assert elm327.mode01_payload(b"41 2F 80 \r\r>", 0x2F) == b"\x80"
    assert elm327.mode01_payload(b"412F80\r\r>", 0x2F) == b"\x80"


def test_mode01_takes_the_first_ecu_and_skips_searching():
    raw = b"SEARCHING...\r410598\r41057B\r\r>"
    assert elm327.mode01_payload(raw, 0x05) == b"\x98"


def test_mode01_no_answer():
    for raw in (b"NO DATA\r\r>", b"CAN ERROR\r\r>", b"UNABLE TO CONNECT\r\r>", b"?\r\r>",
                b"STOPPED\r\r>"):
        assert elm327.mode01_payload(raw, 0x2F) is None


def test_decoders():
    assert PIDS["fuel_level"].decode(b"\x80") == 50.2
    assert PIDS["coolant_temperature"].decode(b"\x7b") == 83
    assert PIDS["odometer"].decode(bytes.fromhex("000A2C2A")) == 66666.6
    assert PIDS["distance_since_codes_cleared"].decode(b"\x01\x2c") == 300


def test_supported_bitmap():
    # BE 1F A8 13 is the datasheet's example: 01 03 04 05 06 07 0C 0D 0E 0F 10 11 13 15 1C 1F 20
    pids = elm327.supported_pids(bytes.fromhex("BE1FA813"), 0)
    assert pids == {0x01, 0x03, 0x04, 0x05, 0x06, 0x07, 0x0C, 0x0D, 0x0E, 0x0F, 0x10, 0x11, 0x13,
                    0x15, 0x1C, 0x1F, 0x20}
    assert elm327.supported_pids(bytes.fromhex("00000001"), 0x80) == {0xA0}


def test_monitor_status():
    assert elm327.decode_monitor_status(bytes.fromhex("83076504")) == (True, 3)
    assert elm327.decode_monitor_status(bytes.fromhex("00076504")) == (False, 0)


def test_dtcs_single_frame_and_none():
    assert elm327.decode_dtcs(b"43010133\r\r>") == ["P0133"]
    assert elm327.decode_dtcs(b"4300\r4300\r\r>") == []
    assert elm327.decode_dtcs(b"NO DATA\r\r>") == []


def test_dtcs_multi_frame():
    raw = b"00E\r0:430601230456\r1:C123D456E789F0\r\r>"
    # Count says 6 but only 5 whole pairs arrived; the dangling F0 is ignored.
    assert elm327.decode_dtcs(raw) == ["P0123", "P0456", "U0123", "U1456", "U2789"]


def test_dtc_letters():
    assert elm327.format_dtc(0x0133) == "P0133"
    assert elm327.format_dtc(0x4123) == "C0123"
    assert elm327.format_dtc(0x8123) == "B0123"
    assert elm327.format_dtc(0xC123) == "U0123"


def test_service_payload_single_frame():
    assert elm327.service_payload(b"622A05B4\r\r>", 0x22, "2A05") == b"\xb4"
    assert elm327.service_payload(b"62 13 10 3A 98 \r\r>", 0x22, "1310") == b"\x3a\x98"
    assert elm327.service_payload(b"613056030000\r\r>", 0x21, "30") == bytes.fromhex("56030000")
    # A different DID, a refusal (request out of range) and silence are all "no value".
    assert elm327.service_payload(b"622A06B4\r\r>", 0x22, "2A05") is None
    assert elm327.service_payload(b"7F2231\r\r>", 0x22, "2A05") is None
    assert elm327.service_payload(b"NO DATA\r\r>", 0x22, "2A05") is None


def test_service_payload_multi_frame_drops_padding():
    # Length 0x0A: 61 06 and eight data bytes; the rest of frame 1 is padding.
    raw = b"00A\r0:6106 8B3F0100\r1:9E3E0100AAAAAA\r\r>"
    assert elm327.service_payload(raw, 0x21, "06") == bytes.fromhex("8B3F01009E3E0100")


class _Recorder(elm327.Elm327):
    """An Elm327 that records commands instead of talking Bluetooth."""

    def __init__(self, replies):
        self._target = None
        self.sent = []
        self._replies = replies

    async def command(self, cmd, timeout=3):
        self.sent.append(cmd)
        return self._replies.get(cmd, b"OK\r\r>")


def test_request_sets_the_module_once_and_broadcast_restores_it():
    elm = _Recorder({"222A05": b"622A05B4\r\r>", "221310": b"7F2231\r\r>"})

    async def run():
        first = await elm.request(0x720, 0x728, 0x22, 0x2A05, 2)
        await elm.request(0x720, 0x728, 0x22, 0x2A06, 2)
        refused = await elm.request(0x7E0, 0x7E8, 0x22, 0x1310, 2)
        await elm.broadcast()
        await elm.broadcast()
        return first, refused

    assert asyncio.run(run()) == (b"\xb4", None)
    assert elm.sent == ["ATSH720", "ATCRA728", "222A05", "222A06",
                        "ATSH7E0", "ATCRA7E8", "221310", "ATSH7DF", "ATCRA"]


def test_request_with_flow_control():
    elm = _Recorder({})

    async def run():
        await elm.request(0x7D6, 0x7DE, 0x21, 0x06, 1, flow_control=True)
        await elm.request(0x7E0, None, 0x22, 0x1310, 2)
        await elm.request(0x750, 0x758, 0x21, 0x30, 1, flow_control=True)
        await elm.broadcast()

    asyncio.run(run())
    assert elm.sent == [
        "ATSH7D6", "ATCRA7DE", "ATFCSH7D6", "ATFCSD300000", "ATFCSM1", "2106",
        "ATSH7E0", "ATCRA", "ATFCSM0", "221310",
        "ATSH750", "ATCRA758", "ATFCSH750", "ATFCSD300000", "ATFCSM1", "2130",
        "ATSH7DF", "ATCRA", "ATFCSM0",
    ]
