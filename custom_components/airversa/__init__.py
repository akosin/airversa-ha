"""AirVersa Scenta XL Home Assistant Integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CONF_ADDRESS, CONF_KEY, CONF_NAME, DOMAIN
from .coordinator import AirVersaCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SWITCH,
    Platform.NUMBER,
    Platform.TIME,
    Platform.SENSOR,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up AirVersa from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    coordinator = AirVersaCoordinator(
        hass,
        device_name=entry.data[CONF_NAME],
        device_address=entry.data.get(CONF_ADDRESS),
        activation_key=entry.data[CONF_KEY],
        entry=entry,
    )

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await coordinator.async_start()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload AirVersa config entry."""
    coordinator: AirVersaCoordinator = hass.data[DOMAIN].get(entry.entry_id)
    if coordinator:
        await coordinator.async_stop()

    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)

    return unloaded
