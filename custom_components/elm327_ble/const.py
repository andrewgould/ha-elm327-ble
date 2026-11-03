"""Constants for the ELM327 Bluetooth LE OBD-II integration."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "elm327_ble"
PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR]

CONF_RUNNING_VOLTAGE = "running_voltage"
CONF_POLL_INTERVAL = "poll_interval"
# The car's OBDb repository ("Mazda-CX-9"), or obdb.GENERIC.
CONF_VEHICLE = "vehicle"
CONF_YEAR = "year"
# The commands picked from the car's signal set by obdb.select(), saved with the
# options so the integration starts without a download.
CONF_SIGNALS = "signals"

# A resting 12 V battery sits at 12.2-12.8 V; an alternator charges at 13.5-14.5 V.
DEFAULT_RUNNING_VOLTAGE = 13.2
# Seconds between battery voltage reads while parked. Only the adapter is asked,
# so this costs nothing on the car's bus; it is how a start is noticed.
DEFAULT_POLL_INTERVAL = 15
# Seconds between OBD reads while the engine runs.
RUNNING_POLL_INTERVAL = 10

# Misses before a manufacturer-specific command is left alone for the rest of a drive.
EXT_TRIES = 3

RETRY_MIN = 5
RETRY_MAX = 120
