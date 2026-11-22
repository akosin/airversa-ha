"""AirVersa time entities: per-schedule start/end. Start == end means all day."""
from __future__ import annotations

from datetime import time as dt_time

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
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
        entities.append(ScheduleTime(coordinator, entry, i, "start"))
        entities.append(ScheduleTime(coordinator, entry, i, "end"))
    async_add_entities(entities)


class ScheduleTime(AirVersaScheduleEntity, TimeEntity):
    def __init__(
        self, coordinator: AirVersaCoordinator, entry: ConfigEntry, index: int, field: str
    ) -> None:
        super().__init__(coordinator, entry, index, field)
        self._field = field
        self._attr_name = f"Schedule {index} {field}"
        self._attr_icon = "mdi:clock-start" if field == "start" else "mdi:clock-end"

    @property
    def native_value(self) -> dt_time | None:
        sched = self.schedule
        return getattr(sched, self._field) if sched else None

    async def async_set_value(self, value: dt_time) -> None:
        await self._update(**{self._field: value.replace(second=0, microsecond=0)})
