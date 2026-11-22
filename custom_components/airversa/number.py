"""AirVersa numbers: per-schedule diffuse and pause durations."""
from __future__ import annotations

import math

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, NUM_SCHEDULES
from .coordinator import AirVersaCoordinator
from .entity import AirVersaScheduleEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: AirVersaCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []
    for i in range(1, NUM_SCHEDULES + 1):
        entities.append(DiffuseNumber(coordinator, entry, i))
        entities.append(PauseNumber(coordinator, entry, i))
    async_add_entities(entities)


class DiffuseNumber(AirVersaScheduleEntity, NumberEntity):
    """How long each burst lasts (seconds)."""

    _attr_icon = "mdi:spray"
    _attr_mode = NumberMode.BOX
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS

    def __init__(self, coordinator: AirVersaCoordinator, entry: ConfigEntry, index: int) -> None:
        super().__init__(coordinator, entry, index, "diffuse")
        self._attr_name = f"Schedule {index} diffuse"

    @property
    def native_min_value(self) -> float:
        return self.coordinator.state.diffuse_min

    @property
    def native_max_value(self) -> float:
        return self.coordinator.state.diffuse_max

    @property
    def native_value(self) -> float | None:
        sched = self.schedule
        return sched.on_time if sched else None

    async def async_set_native_value(self, value: float) -> None:
        await self._update(on_time=int(round(value)))


class PauseNumber(AirVersaScheduleEntity, NumberEntity):
    """Time between bursts (minutes; device stores seconds)."""

    _attr_icon = "mdi:timer-sand"
    _attr_mode = NumberMode.BOX
    _attr_native_step = 0.25
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES

    def __init__(self, coordinator: AirVersaCoordinator, entry: ConfigEntry, index: int) -> None:
        super().__init__(coordinator, entry, index, "pause")
        self._attr_name = f"Schedule {index} pause"

    @property
    def native_min_value(self) -> float:
        # The frontend only accepts min + n*step, so round the device minimum
        # (5 s = 0.083 min) up to a whole step; otherwise 5.0 min is "invalid".
        # Shorter pauses are still possible via airversa.set_schedule.
        steps = math.ceil(self.coordinator.state.pause_min / 60 / self._attr_native_step)
        return max(1, steps) * self._attr_native_step

    @property
    def native_max_value(self) -> float:
        return self.coordinator.state.pause_max / 60

    @property
    def native_value(self) -> float | None:
        sched = self.schedule
        return round(sched.off_time / 60, 2) if sched else None

    async def async_set_native_value(self, value: float) -> None:
        await self._update(off_time=int(round(value * 60)))
