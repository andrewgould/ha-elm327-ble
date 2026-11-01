"""Binary sensors: car in range, adapter connected, engine running, check engine light."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import CarState, Elm327ConfigEntry
from .entity import Elm327Entity


@dataclass(frozen=True, kw_only=True)
class Elm327BinaryDescription(BinarySensorEntityDescription):
    value: Callable[[CarState], bool | None]
    # Only meaningful while connected: a car out of range is probably being driven.
    live: bool = False


BINARY_SENSORS: tuple[Elm327BinaryDescription, ...] = (
    Elm327BinaryDescription(
        key="in_range", value=lambda s: s.in_range, device_class=BinarySensorDeviceClass.PRESENCE,
    ),
    Elm327BinaryDescription(
        key="connected", value=lambda s: s.connected,
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    Elm327BinaryDescription(
        key="engine_running", value=lambda s: s.engine_running, live=True,
        device_class=BinarySensorDeviceClass.RUNNING,
    ),
    Elm327BinaryDescription(
        key="check_engine_light", value=lambda s: s.mil,
        device_class=BinarySensorDeviceClass.PROBLEM,
    ),
)


async def async_setup_entry(hass: HomeAssistant, entry: Elm327ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities(Elm327BinarySensor(entry.runtime_data, d) for d in BINARY_SENSORS)


class Elm327BinarySensor(Elm327Entity, BinarySensorEntity):
    entity_description: Elm327BinaryDescription

    def __init__(self, coordinator, description: Elm327BinaryDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        return not self.entity_description.live or self.coordinator.data.connected

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value(self.coordinator.data)
