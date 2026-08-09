"""Sensors for the City of Waco Water integration."""

from __future__ import annotations

import datetime as dt
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import WacoWaterConfigEntry
from .coordinator import WacoWaterCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WacoWaterConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    async_add_entities([WacoWaterReadingSensor(entry.runtime_data)])


class WacoWaterReadingSensor(
    CoordinatorEntity[WacoWaterCoordinator], SensorEntity
):
    """The meter's cumulative register reading."""

    _attr_device_class = SensorDeviceClass.WATER
    _attr_native_unit_of_measurement = UnitOfVolume.GALLONS
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_has_entity_name = True
    _attr_name = "Meter reading"

    def __init__(self, coordinator: WacoWaterCoordinator) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_reading"
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> float | None:
        """Return the register reading in gallons."""
        return self.coordinator.data.get("reading")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the read timestamp."""
        read_at = self.coordinator.data.get("read_datetime")
        if read_at is None:
            return {}
        return {
            "read_at": dt.datetime.fromtimestamp(
                read_at, tz=dt.UTC
            ).isoformat()
        }
