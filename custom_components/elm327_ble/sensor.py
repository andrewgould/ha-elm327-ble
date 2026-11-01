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
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import CarState, Elm327ConfigEntry
from .entity import Elm327Entity


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


async def async_setup_entry(hass: HomeAssistant, entry: Elm327ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities(Elm327Sensor(entry.runtime_data, d) for d in SENSORS)


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
