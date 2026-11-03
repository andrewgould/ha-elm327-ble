"""Sensors: battery voltage (live) and the last values read from the car."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricPotential,
    UnitOfLength,
    UnitOfPressure,
    UnitOfTemperature,
    UnitOfVolume,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_SIGNALS
from .coordinator import CarState, Elm327ConfigEntry
from .entity import Elm327Entity
from .obdb import keys


@dataclass(frozen=True, kw_only=True)
class Elm327SensorDescription(SensorEntityDescription):
    value: Callable[[CarState], Any]
    # False for values that are only true right now (voltage) rather than last known:
    # those are unavailable while the adapter isn't connected.
    keeps_value: bool = True
    attrs: Callable[[CarState], dict[str, Any]] | None = None


def _car(key: str) -> Callable[[CarState], Any]:
    return lambda s: s.values.get(key)


SENSORS: tuple[Elm327SensorDescription, ...] = (
    Elm327SensorDescription(
        key="battery_voltage", value=lambda s: s.voltage, keeps_value=False,
        device_class=SensorDeviceClass.VOLTAGE, state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT, suggested_display_precision=1,
    ),
    Elm327SensorDescription(
        key="fuel_level", value=_car("fuel_level"), icon="mdi:gas-station",
        state_class=SensorStateClass.MEASUREMENT, native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
    ),
    Elm327SensorDescription(
        key="odometer", value=_car("odometer"), device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        suggested_display_precision=0, icon="mdi:counter",
    ),
    Elm327SensorDescription(
        key="coolant_temperature", value=_car("coolant_temperature"),
        device_class=SensorDeviceClass.TEMPERATURE, state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    Elm327SensorDescription(
        key="oil_temperature", value=_car("oil_temperature"),
        device_class=SensorDeviceClass.TEMPERATURE, state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    Elm327SensorDescription(
        key="ambient_temperature", value=_car("ambient_temperature"),
        device_class=SensorDeviceClass.TEMPERATURE, state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS, entity_registry_enabled_default=False,
    ),
    Elm327SensorDescription(
        key="distance_since_codes_cleared", value=_car("distance_since_codes_cleared"),
        device_class=SensorDeviceClass.DISTANCE, native_unit_of_measurement=UnitOfLength.KILOMETERS,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    Elm327SensorDescription(
        key="distance_with_mil", value=_car("distance_with_mil"),
        device_class=SensorDeviceClass.DISTANCE, native_unit_of_measurement=UnitOfLength.KILOMETERS,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    Elm327SensorDescription(
        key="trouble_codes", value=lambda s: None if s.dtcs is None else len(s.dtcs),
        icon="mdi:car-wrench", attrs=lambda s: {"codes": s.dtcs or []},
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    Elm327SensorDescription(
        key="last_read", value=lambda s: s.last_read, device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


WHEELS = ("front_left", "front_right", "rear_left", "rear_right")

# Manufacturer-specific values, created only when the chosen car's OBDb signal set
# offers them (see obdb.METRICS).
EXTENDED_SENSORS: tuple[Elm327SensorDescription, ...] = (
    *(Elm327SensorDescription(
        key=f"tyre_pressure_{wheel}", value=_car(f"tyre_pressure_{wheel}"),
        device_class=SensorDeviceClass.PRESSURE, state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPressure.KPA, suggested_display_precision=0,
        icon="mdi:car-tire-alert",
    ) for wheel in WHEELS),
    *(Elm327SensorDescription(
        key=f"tyre_temperature_{wheel}", value=_car(f"tyre_temperature_{wheel}"),
        device_class=SensorDeviceClass.TEMPERATURE, state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_registry_enabled_default=False,
    ) for wheel in WHEELS),
    Elm327SensorDescription(
        key="fuel_remaining", value=_car("fuel_remaining"), icon="mdi:gas-station",
        device_class=SensorDeviceClass.VOLUME_STORAGE, state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfVolume.LITERS, suggested_display_precision=0,
    ),
    Elm327SensorDescription(
        key="transmission_temperature", value=_car("transmission_temperature"),
        device_class=SensorDeviceClass.TEMPERATURE, state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS, suggested_display_precision=0,
    ),
    *(Elm327SensorDescription(
        key=key, value=_car(key), icon=icon, device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfLength.KILOMETERS, suggested_display_precision=0,
    ) for key, icon in (("fuel_range", "mdi:gas-station"), ("electric_range", "mdi:ev-station"),
                        ("distance_to_service", "mdi:wrench-clock"))),
    Elm327SensorDescription(
        key="state_of_charge", value=_car("state_of_charge"),
        device_class=SensorDeviceClass.BATTERY, state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE, suggested_display_precision=0,
    ),
    Elm327SensorDescription(
        key="state_of_health", value=_car("state_of_health"), icon="mdi:battery-heart-variant",
        state_class=SensorStateClass.MEASUREMENT, native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0, entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(hass: HomeAssistant, entry: Elm327ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    coordinator = entry.runtime_data
    offered = keys(entry.options.get(CONF_SIGNALS, []))
    async_add_entities(
        Elm327Sensor(coordinator, d)
        for d in (*SENSORS, *(d for d in EXTENDED_SENSORS if d.key in offered)))


class Elm327Sensor(Elm327Entity, SensorEntity):
    entity_description: Elm327SensorDescription

    def __init__(self, coordinator, description: Elm327SensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        return self.entity_description.keeps_value or self.coordinator.data.connected

    @property
    def native_value(self) -> Any:
        return self.entity_description.value(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attrs:
            return self.entity_description.attrs(self.coordinator.data)
        return None
