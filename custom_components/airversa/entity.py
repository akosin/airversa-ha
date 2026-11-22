"""Base entity for AirVersa."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ADDRESS, CONF_NAME, DOMAIN
from .coordinator import AirVersaCoordinator, Schedule


class AirVersaEntity(CoordinatorEntity[AirVersaCoordinator]):
    """Common device info / availability."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: AirVersaCoordinator, entry: ConfigEntry, key: str) -> None:
        super().__init__(coordinator)
        address = (entry.data.get(CONF_ADDRESS) or "").replace(":", "").upper()
        self._attr_unique_id = f"{DOMAIN}_{address}_{key}"
        ble_address = entry.data.get(CONF_ADDRESS)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, ble_address or entry.entry_id)},
            connections={(CONNECTION_BLUETOOTH, ble_address)} if ble_address else set(),
            name=entry.title or entry.data.get(CONF_NAME) or "AirVersa",
            manufacturer="AirVersa",
            model="Scenta XL",
        )

    @property
    def available(self) -> bool:
        return self.coordinator.state.available

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()


class AirVersaScheduleEntity(AirVersaEntity):
    """An entity bound to one schedule slot."""

    def __init__(
        self, coordinator: AirVersaCoordinator, entry: ConfigEntry, index: int, key: str
    ) -> None:
        super().__init__(coordinator, entry, f"schedule_{index}_{key}")
        self._index = index

    @property
    def schedule(self) -> Schedule | None:
        return self.coordinator.state.schedules.get(self._index)

    @property
    def available(self) -> bool:
        return self.coordinator.state.available and self.schedule is not None

    async def _update(self, **changes) -> None:
        await self.coordinator.async_update_schedule(self._index, **changes)
