"""AirVersa sensors: what's running and the live countdown."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import AirVersaCoordinator
from .entity import AirVersaEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: AirVersaCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            ActiveScheduleSensor(coordinator, entry),
            PhaseSensor(coordinator, entry),
            PhaseRemainingSensor(coordinator, entry),
            NextBurstSensor(coordinator, entry),
        ]
    )


class ActiveScheduleSensor(AirVersaEntity, SensorEntity):
    _attr_name = "Active schedule"
    _attr_icon = "mdi:calendar-check"

    def __init__(self, coordinator: AirVersaCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "active_schedule")

    @property
    def native_value(self) -> str:
        s = self.coordinator.state
        if s.phase == "idle":
            return "None"
        return f"Schedule {s.active_slot}"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        s = self.coordinator.state
        sched = s.schedules.get(s.active_slot)
        if not sched or s.phase == "idle":
            return {"slot": 0}
        return {
            "slot": sched.index,
            "diffuse_seconds": sched.on_time,
            "pause_seconds": sched.off_time,
        }


class PhaseSensor(AirVersaEntity, SensorEntity):
    _attr_name = "Phase"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["idle", "diffusing", "paused"]

    def __init__(self, coordinator: AirVersaCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "phase")

    @property
    def native_value(self) -> str:
        return self.coordinator.state.phase

    @property
    def icon(self) -> str:
        return {
            "diffusing": "mdi:weather-windy",
            "paused": "mdi:pause-circle-outline",
        }.get(self.coordinator.state.phase, "mdi:sleep")


class PhaseRemainingSensor(AirVersaEntity, SensorEntity):
    """Live countdown for the current diffuse/pause phase (ticks every second)."""

    _attr_name = "Phase time remaining"
    _attr_icon = "mdi:timer-outline"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS

    def __init__(self, coordinator: AirVersaCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "phase_remaining")

    @property
    def native_value(self) -> int | None:
        return self.coordinator.state.phase_remaining


class NextBurstSensor(AirVersaEntity, SensorEntity):
    """When the next burst starts. Dashboards render this as a live 'in 3 minutes'."""

    _attr_name = "Next burst"
    _attr_icon = "mdi:timer-play-outline"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: AirVersaCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "next_burst")

    @property
    def native_value(self) -> datetime | None:
        # While diffusing, this is end of the current burst + the pause.
        return self.coordinator.state.next_burst

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        ends = self.coordinator.state.phase_ends
        return {"phase_ends": ends.isoformat() if ends else None}
