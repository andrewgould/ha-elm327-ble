# Changelog

Versions follow [semantic versioning](https://semver.org/). The version in
`manifest.json` is what HACS installs, and each release tag must match it.

## 1.2.0

- **Any car OBDb knows.** The **Vehicle** option now lists the 467 cars whose
  [OBDb](https://github.com/OBDb) signal sets have readings this integration
  can use. Picking one downloads its signal set once and saves the commands
  with the options. Cars whose commands differ by model year ask for the year.
- Readings come from what OBDb marks as everyday metrics: tyre pressure and
  temperature, fuel level and litres, odometer, fuel and electric range,
  distance to service, coolant, oil and transmission temperature, and an EV's
  state of charge and battery health. Units are converted to kPa, °C, km, L.
- Service 21 as well as 22, multi-frame replies, and modules that need their
  own flow control address.
- Only the Mazda CX-9 is tested; other cars' decoding is checked against
  OBDb's recorded test cases.
- An existing **Mazda CX-9, second generation** choice moves to OBDb's
  Mazda-CX-9 signal set on the first start, keeping the same sensors.

## 1.1.0

- **Vehicle profiles.** A new **Vehicle** option reads manufacturer-specific
  (service 22) values on top of standard OBD-II. The first profile is the
  second-generation Mazda CX-9 (2016-2024): tyre pressure and temperature for
  each wheel, fuel remaining in litres, oil temperature and transmission
  temperature. Commands and scaling are from [OBDb](https://github.com/OBDb).
  The default stays standard OBD-II only, so nothing changes until a vehicle
  is picked.
- Changing the options now reloads the integration.

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
