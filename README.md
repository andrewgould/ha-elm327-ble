# ELM327 OBD-II (Bluetooth LE) for Home Assistant

Reads a car through a cheap ELM327 Bluetooth LE OBD-II dongle (built against a
Veepeak OBDCheck BLE) using Home Assistant's own Bluetooth, so an ESPHome
Bluetooth proxy within reach of the parked car is all it needs.

## What it does

It keeps a connection to the dongle while the car is in range and reads the
**battery voltage** from the dongle every 15 seconds. That reading is measured
by the dongle at the OBD port and sends nothing to the car.

It only queries the car (mode 01 PIDs, stored trouble codes) **while the
voltage says the alternator is charging** (13.2 V by default, adjustable in the
options). Asking a parked car's sleeping CAN bus for data can wake its modules,
and a parked car has nothing new to say anyway. So expect car data at the start
and end of each drive, while the car is still near the proxy.

Values read from the car are kept and survive restarts, so fuel level and
odometer always show the last known reading, with **Last read from car** saying
when that was.

| Entity | Notes |
| --- | --- |
| In range | The dongle is advertising or connected: the car is home |
| Adapter connected | Diagnostic |
| Engine running | Voltage at or above the threshold. Unavailable while not connected |
| Battery voltage | Live, unavailable while not connected |
| Fuel level, odometer, coolant / oil / outside temperature | Last known, if the car supports the PID |
| Check engine light, trouble codes (count, `codes` attribute) | Last known |
| Distance since codes cleared, distance with check engine light on | Diagnostic |

PIDs the car doesn't list as supported are never asked for, and their
sensors stay unknown.

## Setup

Copy `custom_components/elm327_ble` into Home Assistant's `custom_components`
and restart, then add **ELM327 OBD-II (Bluetooth LE)** and pick the dongle.
Close the phone app first: the dongle takes one connection at a time.

Supported GATT layouts: service FFF0 (notify FFF1, write FFF2), FFE0 (FFE1)
and 18F0 (18F1/18F2).

## Caveats

- The dongle draws a little current from the car battery all the time it is
  plugged in. Watch **Battery voltage** after the car has been parked for a
  long time.
- A battery charger or maintainer pushes the voltage over the threshold, and
  the integration will then query the car as if the engine were running.
