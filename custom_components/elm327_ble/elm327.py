"""ELM327 over Bluetooth LE: framing, OBD-II decoding and a small async client.

Nothing in here imports Home Assistant, so the parsing can be tested on its own.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from dataclasses import dataclass

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic

PROMPT = b">"

# (service, notify characteristic, write characteristic). The same short UUID
# can appear in more than one service (the Veepeak has a second FFF1 in a vendor
# service), so characteristics are always looked up through their service.
KNOWN_LAYOUTS = (
    ("0000fff0-0000-1000-8000-00805f9b34fb",
     "0000fff1-0000-1000-8000-00805f9b34fb", "0000fff2-0000-1000-8000-00805f9b34fb"),
    ("0000ffe0-0000-1000-8000-00805f9b34fb",
     "0000ffe1-0000-1000-8000-00805f9b34fb", "0000ffe1-0000-1000-8000-00805f9b34fb"),
    ("000018f0-0000-1000-8000-00805f9b34fb",
     "000018f1-0000-1000-8000-00805f9b34fb", "000018f2-0000-1000-8000-00805f9b34fb"),
)
KNOWN_SERVICES = {layout[0] for layout in KNOWN_LAYOUTS}


class Elm327Error(Exception):
    """The adapter didn't answer, or answered with something unusable."""


@dataclass(frozen=True)
class Pid:
    """A mode 01 PID this integration reads."""

    key: str
    pid: int
    size: int
    decode: Callable[[bytes], float | int]


PIDS: tuple[Pid, ...] = (
    Pid("coolant_temperature", 0x05, 1, lambda d: d[0] - 40),
    Pid("distance_with_mil", 0x21, 2, lambda d: d[0] << 8 | d[1]),
    Pid("fuel_level", 0x2F, 1, lambda d: round(d[0] * 100 / 255, 1)),
    Pid("distance_since_codes_cleared", 0x31, 2, lambda d: d[0] << 8 | d[1]),
    Pid("ambient_temperature", 0x46, 1, lambda d: d[0] - 40),
    Pid("oil_temperature", 0x5C, 1, lambda d: d[0] - 40),
    Pid("odometer", 0xA6, 4, lambda d: int.from_bytes(d[:4], "big") / 10),
)


def clean_lines(raw: bytes) -> list[str]:
    """Split a reply into upper-case lines without spaces, prompt or noise."""
    text = raw.decode("ascii", "ignore").replace(">", "")
    lines = []
    for line in re.split(r"[\r\n]+", text):
        line = line.strip().upper()
        if not line or line.startswith("SEARCHING"):
            continue
        lines.append(line.replace(" ", ""))
    return lines


def mode01_payload(raw: bytes, pid: int) -> bytes | None:
    """Data bytes of the first ECU's answer to `01 <pid>`, or None if nobody answered."""
    prefix = f"41{pid:02X}"
    for line in clean_lines(raw):
        if line.startswith(prefix) and re.fullmatch(r"[0-9A-F]+", line):
            data = line[len(prefix):]
            return bytes.fromhex(data[: len(data) // 2 * 2])
    return None


def service_payload(raw: bytes, service: int, pid: str) -> bytes | None:
    """Data bytes after the echo in the answer to `<service> <pid>` (21 or 22, from one
    module), single or multi-frame. None for no answer or a 7F refusal."""
    prefix = f"{service + 0x40:02X}{pid}"
    for msg in _messages(clean_lines(raw)):
        if msg.startswith(prefix) and re.fullmatch(r"[0-9A-F]+", msg):
            data = msg[len(prefix):]
            return bytes.fromhex(data[: len(data) // 2 * 2])
    return None


def supported_pids(payload: bytes, base: int) -> set[int]:
    """Decode a 4-byte "PIDs supported" bitmap answered for PID `base`."""
    bits = int.from_bytes(payload[:4], "big")
    return {base + 1 + i for i in range(32) if bits & (1 << (31 - i))}


def decode_monitor_status(payload: bytes) -> tuple[bool, int]:
    """PID 01: (check engine light on, number of stored codes)."""
    return bool(payload[0] & 0x80), payload[0] & 0x7F


def _messages(lines: list[str]) -> list[str]:
    """Reassemble ISO-TP multi-frame replies ("00E", "0:...", "1:...") into hex strings,
    cut to the announced length so the last frame's padding is dropped."""
    messages: list[str] = []
    frames: list[str] = []
    length: int | None = None

    def flush() -> None:
        if frames:
            joined = "".join(frames)
            messages.append(joined[: length * 2] if length else joined)
            frames.clear()

    for line in lines:
        if m := re.fullmatch(r"([0-9A-F]):([0-9A-F]+)", line):
            frames.append(m.group(2))
        elif re.fullmatch(r"[0-9A-F]{3}", line):
            flush()
            length = int(line, 16)
        else:
            flush()
            length = None
            messages.append(line)
    flush()
    return messages


def format_dtc(code: int) -> str:
    return "PCBU"[code >> 14] + f"{code >> 12 & 3}{code & 0xFFF:03X}"


def decode_dtcs(raw: bytes) -> list[str]:
    """Stored trouble codes from a mode 03 reply (CAN: 43, count, then 2-byte codes)."""
    codes: list[str] = []
    for msg in _messages(clean_lines(raw)):
        if not msg.startswith("43") or not re.fullmatch(r"[0-9A-F]+", msg):
            continue
        data = bytes.fromhex(msg[: len(msg) // 2 * 2])
        count = data[1] if len(data) > 1 else 0
        for i in range(count):
            pair = data[2 + 2 * i: 4 + 2 * i]
            if len(pair) == 2 and (code := pair[0] << 8 | pair[1]) and (
                    dtc := format_dtc(code)) not in codes:
                codes.append(dtc)
    return codes


def parse_voltage(raw: bytes) -> float:
    for line in clean_lines(raw):
        if m := re.fullmatch(r"(\d+(?:\.\d+)?)V", line):
            return float(m.group(1))
    raise Elm327Error(f"unexpected ATRV reply {raw!r}")


def find_characteristics(
    client: BleakClient,
) -> tuple[BleakGATTCharacteristic, BleakGATTCharacteristic]:
    """The adapter's (notify, write) characteristics."""
    for service_uuid, rx_uuid, tx_uuid in KNOWN_LAYOUTS:
        if service := client.services.get_service(service_uuid):
            rx, tx = service.get_characteristic(rx_uuid), service.get_characteristic(tx_uuid)
            if rx and tx:
                return rx, tx
    raise Elm327Error("no known ELM327 serial service on this device")


class Elm327:
    """One command at a time over a connected BleakClient."""

    def __init__(self, client: BleakClient) -> None:
        self._client = client
        self._rx, self._tx = find_characteristics(client)
        self._buffer = bytearray()
        self._prompt = asyncio.Event()
        self._lock = asyncio.Lock()
        # (header, rx, flow control) set for one module's service 21/22 requests, or
        # None for the default functional (broadcast) address that mode 01 and 03 use.
        self._target: tuple[int, int | None, bool] | None = None

    def _on_notify(self, _: BleakGATTCharacteristic, data: bytearray) -> None:
        self._buffer.extend(data)
        if PROMPT in data:
            self._prompt.set()

    async def start(self) -> str:
        """Subscribe and reset the adapter to terse output. Returns its version string."""
        await self._client.start_notify(self._rx, self._on_notify)
        reply = (await self.command("ATZ", timeout=5)).decode("ascii", "ignore")
        self._target = None
        for cmd in ("ATE0", "ATL0", "ATS0", "ATH0"):
            await self.command(cmd)
        return next((line.strip() for line in reply.split("\r") if line.strip().startswith("ELM")),
                    "ELM327")

    async def command(self, cmd: str, timeout: float = 3) -> bytes:
        async with self._lock:
            self._buffer.clear()
            self._prompt.clear()
            data = (cmd + "\r").encode()
            response = "write" in self._tx.properties
            for i in range(0, len(data), 20):
                await self._client.write_gatt_char(self._tx, data[i:i + 20], response=response)
            try:
                async with asyncio.timeout(timeout):
                    await self._prompt.wait()
            except TimeoutError as err:
                raise Elm327Error(f"no prompt after {cmd!r}") from err
            return bytes(self._buffer)

    async def voltage(self) -> float:
        """Battery voltage at the OBD port. Measured by the adapter: no traffic to the car."""
        return parse_voltage(await self.command("ATRV"))

    async def mode01(self, pid: int, timeout: float = 3) -> bytes | None:
        return mode01_payload(await self.command(f"01{pid:02X}", timeout), pid)

    async def request(self, header: int, rx: int | None, service: int, pid: int,
                      pid_bytes: int, flow_control: bool = False) -> bytes | None:
        """Ask one module for a service 21 or 22 value. Call broadcast() when done.

        `rx` is the address the module answers from (None: any). With `flow_control`
        the adapter sends flow control frames for multi-frame replies to `header`
        itself, for modules whose request and reply addresses aren't 8 apart.
        """
        target = (header, rx, flow_control)
        if self._target != target:
            await self.command(f"ATSH{header:03X}")
            await self.command(f"ATCRA{rx:03X}" if rx is not None else "ATCRA")
            if flow_control:
                await self.command(f"ATFCSH{header:03X}")
                await self.command("ATFCSD300000")
                await self.command("ATFCSM1")
            elif self._target and self._target[2]:
                await self.command("ATFCSM0")
            self._target = target
        pid_hex = f"{pid:0{pid_bytes * 2}X}"
        return service_payload(await self.command(f"{service:02X}{pid_hex}"), service, pid_hex)

    async def broadcast(self) -> None:
        """Back to the functional address and any receiver, for mode 01 and 03."""
        if self._target is not None:
            await self.command("ATSH7DF")
            await self.command("ATCRA")
            if self._target[2]:
                await self.command("ATFCSM0")
            self._target = None

    async def supported(self) -> set[int]:
        """Walk the "PIDs supported" chain (00, 20, 40 ...) as far as the car goes."""
        pids: set[int] = set()
        for base in range(0x00, 0xE0, 0x20):
            if base and base not in pids:
                break
            # The first query may trigger a protocol search, which takes a while.
            payload = await self.mode01(base, timeout=10 if base == 0 else 3)
            if payload is None or len(payload) < 4:
                break
            pids |= supported_pids(payload, base)
        return pids

    async def dtcs(self) -> list[str]:
        return decode_dtcs(await self.command("03", timeout=5))
