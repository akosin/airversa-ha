"""AirVersa switches: master power + per-schedule enable."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DAY_BITS, DOMAIN, NUM_SCHEDULES
from .coordinator import AirVersaCoordinator
from .entity import AirVersaEntity, AirVersaScheduleEntity

SERVICE_SET_SCHEDULE = "set_schedule"

SET_SCHEDULE_SCHEMA = {
    vol.Optional("enabled"): cv.boolean,
    vol.Optional("start"): cv.time,
    vol.Optional("end"): cv.time,
    vol.Optional("days"): vol.All(cv.ensure_list, [vol.In(list(DAY_BITS))]),
    vol.Optional("diffuse_seconds"): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
    vol.Optional("pause_seconds"): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: AirVersaCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SwitchEntity] = [
        AirVersaPowerSwitch(coordinator, entry),
    ]
    entities += [
        AirVersaScheduleSwitch(coordinator, entry, i) for i in range(1, NUM_SCHEDULES + 1)
    ]
    async_add_entities(entities)

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_SET_SCHEDULE, SET_SCHEDULE_SCHEMA, "async_set_schedule"
    )


class AirVersaPowerSwitch(AirVersaEntity, SwitchEntity):
    """Master enable. Schedules only run while this is on."""

    _attr_name = "Power"
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_icon = "mdi:air-humidifier"

    def __init__(self, coordinator: AirVersaCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "power")

    @property
    def is_on(self) -> bool:
        return self.coordinator.state.powered_on

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        s = self.coordinator.state
        return {"firmware": s.firmware, "model": s.model, "version": s.version}

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_power(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_power(False)


class AirVersaScheduleSwitch(AirVersaScheduleEntity, SwitchEntity):
    """Enable/disable one schedule slot."""

    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator: AirVersaCoordinator, entry: ConfigEntry, index: int) -> None:
        super().__init__(coordinator, entry, index, "enabled")
        self._attr_name = f"Schedule {index}"

    @property
    def is_on(self) -> bool | None:
        sched = self.schedule
        return bool(sched and sched.shown and sched.enabled)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        sched = self.schedule
        if sched is None:
            return {}
        return {
            "configured": sched.shown,
            "start": sched.start.strftime("%H:%M"),
            "end": sched.end.strftime("%H:%M"),
            "all_day": sched.all_day,
            "days": sched.day_list,
            "diffuse_seconds": sched.on_time,
            "pause_seconds": sched.off_time,
            "running": self.coordinator.state.active_slot == self._index,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._update(enabled=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._update(enabled=False)

    async def async_set_schedule(self, **kwargs: Any) -> None:
        changes: dict[str, Any] = {}
        for src, dst in (
            ("enabled", "enabled"),
            ("start", "start"),
            ("end", "end"),
            ("days", "days"),
            ("diffuse_seconds", "on_time"),
            ("pause_seconds", "off_time"),
        ):
            if src in kwargs:
                changes[dst] = kwargs[src]
        if changes:
            await self._update(**changes)
