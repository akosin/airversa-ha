"""Config flow for AirVersa diffusers."""
from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import CONF_ADDRESS, CONF_KEY, CONF_NAME, DEFAULT_KEY, DOMAIN, NAME_PREFIX
from .coordinator import async_validate_key

_LOGGER = logging.getLogger(__name__)


def _title(name: str) -> str:
    """'SP_ANW_00001A2B' -> 'AirVersa 1A2B'."""
    return f"AirVersa {name[-4:]}" if name.startswith(NAME_PREFIX) else name


def _key_schema(default: str = DEFAULT_KEY) -> vol.Schema:
    return vol.Schema({vol.Required(CONF_KEY, default=default): str})


def _clean_key(raw: str) -> str | None:
    key = raw.strip()
    return key if len(key) == 4 and key.isdigit() else None


class AirVersaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Discover AirVersa diffusers over Bluetooth and check the activation code."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovery: BluetoothServiceInfoBleak | None = None
        self._discovered: dict[str, BluetoothServiceInfoBleak] = {}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _name_configured(self, name: str) -> bool:
        """Entries made before discovery existed are keyed by name, not address."""
        return any(
            entry.data.get(CONF_NAME) == name or entry.unique_id == name
            for entry in self._async_current_entries(include_ignore=False)
        )

    async def _validate(
        self, info: BluetoothServiceInfoBleak, raw_key: str
    ) -> tuple[str | None, str | None]:
        """Return (key, error)."""
        key = _clean_key(raw_key)
        if key is None:
            return None, "invalid_format"
        device = bluetooth.async_ble_device_from_address(
            self.hass, info.address, connectable=True
        ) or info.device
        error = await async_validate_key(device, key)
        return key, error

    def _create(self, info: BluetoothServiceInfoBleak, key: str) -> ConfigFlowResult:
        return self.async_create_entry(
            title=_title(info.name),
            data={CONF_NAME: info.name, CONF_ADDRESS: info.address, CONF_KEY: key},
        )

    # ------------------------------------------------------------------
    # Automatic discovery
    # ------------------------------------------------------------------

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        if self._name_configured(discovery_info.name):
            return self.async_abort(reason="already_configured")
        self._discovery = discovery_info
        self.context["title_placeholders"] = {"name": _title(discovery_info.name)}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._discovery is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            key, error = await self._validate(self._discovery, user_input[CONF_KEY])
            if error is None and key is not None:
                return self._create(self._discovery, key)
            errors["base"] = error or "unknown"

        return self.async_show_form(
            step_id="bluetooth_confirm",
            data_schema=_key_schema(),
            description_placeholders={
                "name": _title(self._discovery.name),
                "ble_name": self._discovery.name,
            },
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Manual: pick from devices HA can currently see
    # ------------------------------------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            info = self._discovered[address]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            key, error = await self._validate(info, user_input[CONF_KEY])
            if error is None and key is not None:
                return self._create(info, key)
            errors["base"] = error or "unknown"

        configured = self._async_current_ids(include_ignore=False)
        self._discovered = {
            info.address: info
            for info in bluetooth.async_discovered_service_info(self.hass, connectable=True)
            if info.name
            and info.name.startswith(NAME_PREFIX)
            and info.address not in configured
            and not self._name_configured(info.name)
        }
        if not self._discovered:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): vol.In(
                        {
                            addr: f"{_title(info.name)} ({info.name})"
                            for addr, info in self._discovered.items()
                        }
                    ),
                    vol.Required(CONF_KEY, default=DEFAULT_KEY): str,
                }
            ),
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Re-auth: the device rejected the stored code
    # ------------------------------------------------------------------

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            key = _clean_key(user_input[CONF_KEY])
            if key is None:
                errors["base"] = "invalid_format"
            else:
                address = entry.data.get(CONF_ADDRESS)
                device = None
                if address:
                    device = bluetooth.async_ble_device_from_address(
                        self.hass, address, connectable=True
                    )
                else:
                    for info in bluetooth.async_discovered_service_info(
                        self.hass, connectable=True
                    ):
                        if info.name == entry.data.get(CONF_NAME):
                            device = info.device
                            break
                if device is None:
                    errors["base"] = "cannot_connect"
                else:
                    error = await async_validate_key(device, key)
                    if error is None:
                        return self.async_update_reload_and_abort(
                            entry, data_updates={CONF_KEY: key}
                        )
                    errors["base"] = error

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_key_schema(""),
            description_placeholders={"name": entry.title},
            errors=errors,
        )
