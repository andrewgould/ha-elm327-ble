# Changelog

Versions follow [semantic versioning](https://semver.org/). The version in
`manifest.json` is what HACS installs, and each release tag must match it.

## 1.0.0

First release.

- Connects to an ELM327 Bluetooth LE OBD-II adapter through Home Assistant's
  Bluetooth, including ESPHome Bluetooth proxies, and keeps the connection while
  the car is in range.
- Reads battery voltage from the adapter every 15 seconds without talking to the
  car. Queries the car (mode 01 PIDs and stored trouble codes) only while the
  voltage says the engine is running, so a parked car's CAN bus is never woken.
- Fuel level, odometer, coolant, oil and outside temperature, check engine light,
  trouble codes and the two distance counters, each kept as the last known value
  across restarts. PIDs the car doesn't support are never asked for.
- In range, adapter connected and engine running binary sensors.
- Running voltage threshold and parked poll interval in the options.
- Ships its own icon (shown on Home Assistant 2026.3 and later).
- Tested with a Veepeak OBDCheck BLE (ELM327 v2.2) in a 2022 Mazda CX-9.
