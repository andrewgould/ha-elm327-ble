"""Base entity for the car."""

from __future__ import annotations

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import Elm327Coordinator


class Elm327Entity(CoordinatorEntity[Elm327Coordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: Elm327Coordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.address}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = coordinator.device_info
