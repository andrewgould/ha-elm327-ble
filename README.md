<img src="custom_components/elm327_ble/brand/icon@2x.png" alt="" width="96" align="right">

# ELM327 OBD-II (Bluetooth LE) for Home Assistant

[![Validate](https://github.com/andrewgould/ha-elm327-ble/actions/workflows/validate.yml/badge.svg)](https://github.com/andrewgould/ha-elm327-ble/actions/workflows/validate.yml)
[![Release](https://img.shields.io/github/v/release/andrewgould/ha-elm327-ble)](https://github.com/andrewgould/ha-elm327-ble/releases)

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

## Vehicle profiles

Some cars offer more than standard OBD-II through manufacturer-specific
(service 22) requests to individual modules. Pick the car under **Configure →
Vehicle** to read those as well:

| Vehicle | Extra sensors |
| --- | --- |
| Mazda CX-9, second generation (2016-2024) | Tyre pressure for each wheel, tyre temperature for each wheel (disabled by default), fuel remaining in litres, oil temperature, transmission temperature |

These are only asked for while the engine runs, like everything else from the
car. A value the car doesn't answer three times in a row is left alone until
the next drive.

The commands and scaling come from [OBDb](https://github.com/OBDb), the open
vehicle signal database also used by the Pelican and Sidecar apps, licensed
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). Adding
another car is a matter of a new entry in `vehicles.py`.

## Install

Through [HACS](https://hacs.xyz), as a custom repository:

[![Open in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=andrewgould&repository=ha-elm327-ble&category=integration)

Or in HACS, **⋮ → Custom repositories**, add
`https://github.com/andrewgould/ha-elm327-ble` as an **Integration**, then
download **ELM327 OBD-II (Bluetooth LE)** and restart Home Assistant.

Without HACS, unzip `elm327_ble.zip` from the
[latest release](https://github.com/andrewgould/ha-elm327-ble/releases/latest)
into `custom_components/elm327_ble` and restart.

## Setup

Add **ELM327 OBD-II (Bluetooth LE)** under **Settings → Devices & services**
and pick the dongle from the list (or type its Bluetooth address). Close the
phone app first: the dongle takes one connection at a time.

The car needs to be within reach of a Bluetooth adapter or an
[ESPHome Bluetooth proxy](https://esphome.io/components/bluetooth_proxy.html)
with active connections enabled. A proxy holds three connections at most, and
this integration keeps one of them for as long as the car is home.

Supported GATT layouts: service FFF0 (notify FFF1, write FFF2), FFE0 (FFE1)
and 18F0 (18F1/18F2).

## Tested with

- Veepeak OBDCheck BLE (reports itself as ELM327 v2.2, service FFF0)
- 2022 Mazda CX-9 (ISO 15765-4 CAN, 11 bit, 500 kbaud). It offers fuel level,
  odometer and coolant temperature, but not oil or outside temperature.
- An ESPHome Bluetooth proxy on an ESP32-S3, indoors and through a wall from the garage (about -85 dBm)
- Home Assistant 2026.10

Other ELM327 BLE adapters using the layouts above should work. Issues with the
adapter and car named are welcome.

## Caveats

- The dongle draws a little current from the car battery all the time it is
  plugged in. Watch **Battery voltage** after the car has been parked for a
  long time.
- A battery charger or maintainer pushes the voltage over the threshold, and
  the integration will then query the car as if the engine were running.

## Releasing

Bump `version` in `manifest.json`, add a matching `## X.Y.Z` section to
`CHANGELOG.md`, then tag and push:

```
git tag vX.Y.Z && git push origin vX.Y.Z
```

The Release workflow checks the tag against the manifest, runs the tests,
builds `elm327_ble.zip` and publishes the release with that changelog section
as its notes. HACS installs from the zip.

The icon is drawn by `assets/make_icons.py`, which writes the PNGs into the
integration's `brand/` folder.
