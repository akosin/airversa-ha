"""BLE connection coordinator for AirVersa Scenta XL."""
from __future__ import annotations

import asyncio
import dataclasses
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, time as dt_time, timedelta

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    ACK_MASK,
    ACK_ON_RECEIVE,
    AK_CHAR_UUID,
    CMD_LOGIN,
    CMD_SCHED_ACK,
    CMD_SCHEDULE,
    CMD_TIME_SYNC,
    CMD_TOTAL_CTRL,
    CTRL_OFF,
    CTRL_ON,
    DAY_BITS,
    DAY_ORDER,
    DEFAULT_DIFFUSE_MAX,
    DEFAULT_DIFFUSE_MIN,
    DEFAULT_PAUSE_MIN,
    FAN_OFF_VAL,
    FAN_ON_VAL,
    KEEPALIVE_INTERVAL_S,
    KEEPALIVE_PACKET,
    NUM_SCHEDULES,
    PAIR_CODE,
    PAUSE_MAX,
    PKT_DEVICE_MODEL,
    PKT_LIMITS,
    PKT_LOGIN_RESULT,
    PKT_SCHEDULE,
    PKT_SET_COMPLETE,
    PKT_TOTAL_CTRL,
    PKT_VERSION,
    PKT_WORKING_SCHED,
)

_LOGGER = logging.getLogger(__name__)

RECONNECT_DELAY_S = 5.0
LOGIN_TIMEOUT_S = 8.0
WRITE_ACK_TIMEOUT_S = 4.0
HEARTBEAT_STALE_S = 5.0
# Keep entities available this long after a drop so quick reconnects don't flicker
AVAILABILITY_GRACE_S = 30.0
# Ignore next-burst timestamp shifts smaller than this (BLE jitter)
TIMESTAMP_JITTER_S = 2.0


def _login_packet(key: str) -> bytes:
    return bytes([CMD_LOGIN]) + (key + PAIR_CODE).encode("utf-8")


def _login_rejected(data: bytes) -> bool:
    return data[1:min(12, len(data))].decode("utf-8", errors="replace").startswith("ERROR")


async def async_validate_key(device: BLEDevice, key: str) -> str | None:
    """Connect once and try the activation code.

    Returns None on success, or an error key: "invalid_key" / "cannot_connect".
    """
    loop = asyncio.get_running_loop()
    result: asyncio.Future[bytes] = loop.create_future()

    def _on_notify(_sender, data: bytearray) -> None:
        if data and data[0] == PKT_LOGIN_RESULT and not result.done():
            result.set_result(bytes(data))

    try:
        client = await establish_connection(
            BleakClientWithServiceCache, device, device.name or device.address
        )
    except (BleakError, asyncio.TimeoutError, OSError) as exc:
        _LOGGER.debug("AirVersa: validation connect failed: %s", exc)
        return "cannot_connect"
    try:
        await client.start_notify(AK_CHAR_UUID, _on_notify)
        await client.write_gatt_char(AK_CHAR_UUID, _login_packet(key), response=False)
        data = await asyncio.wait_for(result, timeout=LOGIN_TIMEOUT_S)
    except (BleakError, asyncio.TimeoutError, OSError) as exc:
        _LOGGER.debug("AirVersa: validation login failed: %s", exc)
        return "cannot_connect"
    finally:
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass
    return "invalid_key" if _login_rejected(data) else None


# ----------------------------------------------------------------------
# Schedule model
# ----------------------------------------------------------------------


@dataclass
class Schedule:
    """One of the device's schedule slots (ScentScheduleModel, AK/custom variant)."""

    index: int
    aroma: int = 1
    header: int = 0x03       # packet byte 3: bit0 fog, bit1 fan (global)
    shown: bool = False      # slot exists in the app (False = empty slot)
    enabled: bool = False
    fan: bool = True
    start: dt_time = dt_time(0, 0)
    end: dt_time = dt_time(23, 59)
    days: int = 0x7F         # bit0 = Sun … bit6 = Sat
    work_mode: int = 1       # 1 = custom on/off times (ANW has no grade mode)
    grade: int = 1
    on_time: int = 10        # diffuse seconds
    off_time: int = 100      # pause seconds

    @classmethod
    def from_packet(cls, data: bytes) -> "Schedule":
        flags = data[6]
        sched = cls(
            index=data[5],
            aroma=data[1],
            header=data[3],
            shown=bool(flags & 0x01),
            enabled=bool(flags & 0x02),
            fan=bool(flags & 0x04),
            start=dt_time(min(data[7], 23), min(data[8], 59)),
            end=dt_time(min(data[9], 23), min(data[10], 59)),
            days=data[11] & 0x7F,
            work_mode=data[12] & 0x01,
            grade=data[13],
        )
        if len(data) >= 18:
            sched.on_time = (data[14] << 8) | data[15]
            sched.off_time = (data[16] << 8) | data[17]
        return sched

    def to_packet(self) -> bytes:
        """18-byte write, mirroring ScentScheduleModel.writeData (custom=true)."""
        flags = (
            (0x01 if self.shown else 0)
            | (0x02 if (self.enabled and self.shown) else 0)
            | (0x04 if self.fan else 0)
        )
        return bytes(
            [
                CMD_SCHEDULE,
                self.aroma,
                0x02,
                0x01 | (self.header & 0x02),
                0x00,
                self.index,
                flags,
                self.start.hour,
                self.start.minute,
                self.end.hour,
                self.end.minute,
                self.days & 0x7F,
                self.work_mode,
                self.grade,
                (self.on_time >> 8) & 0xFF,
                self.on_time & 0xFF,
                (self.off_time >> 8) & 0xFF,
                self.off_time & 0xFF,
            ]
        )

    @property
    def name(self) -> str:
        return f"Schedule {self.index}"

    @property
    def all_day(self) -> bool:
        return self.start == self.end

    @property
    def day_list(self) -> list[str]:
        return [d for d in DAY_ORDER if self.days & (1 << DAY_BITS[d])]


# ----------------------------------------------------------------------
# Device state
# ----------------------------------------------------------------------


@dataclass
class AirVersaState:
    """Snapshot of device state."""

    connected: bool = False
    logged_in: bool = False
    powered_on: bool = False          # master enable (0x4D byte1 bit0)
    grace_until: float = 0.0          # monotonic time; stay 'available' until then
    firmware: str = ""
    model: str = ""
    version: str = ""

    # Heartbeat (0x59)
    active_slot: int = 0              # 0 = idle, 1-5 = running schedule
    is_diffusing: bool = False
    phase_remaining: int | None = None  # live countdown (seconds) of current phase
    next_burst: datetime | None = None
    phase_ends: datetime | None = None
    last_heartbeat: float = 0.0

    # Schedules (0x4A)
    schedules: dict[int, Schedule] = field(default_factory=dict)

    # Limits (0x46)
    diffuse_min: int = DEFAULT_DIFFUSE_MIN
    diffuse_max: int = DEFAULT_DIFFUSE_MAX
    pause_min: int = DEFAULT_PAUSE_MIN
    pause_max: int = PAUSE_MAX

    @property
    def online(self) -> bool:
        """Actually connected and logged in (required for writes)."""
        return self.connected and self.logged_in

    @property
    def available(self) -> bool:
        """What entities show: online, or briefly offline while reconnecting."""
        return self.online or time.monotonic() < self.grace_until

    @property
    def schedules_loaded(self) -> bool:
        return self.available and len(self.schedules) >= NUM_SCHEDULES

    @property
    def phase(self) -> str:
        if not self.powered_on or self.active_slot == 0:
            return "idle"
        return "diffusing" if self.is_diffusing else "paused"


# ----------------------------------------------------------------------
# Coordinator
# ----------------------------------------------------------------------


class AirVersaCoordinator(DataUpdateCoordinator[AirVersaState]):
    """Manages the BLE connection and device state for AirVersa Scenta XL."""

    def __init__(
        self,
        hass: HomeAssistant,
        device_name: str,
        device_address: str | None,
        activation_key: str,
        entry: ConfigEntry | None = None,
    ) -> None:
        super().__init__(hass, _LOGGER, name="AirVersa", update_interval=None)
        self.entry = entry
        self.login_rejected = False
        self.device_name = device_name
        self.device_address = device_address
        self.activation_key = activation_key

        self._client: BleakClient | None = None
        self._state = AirVersaState()
        self._connection_task: asyncio.Task | None = None
        self._write_lock = asyncio.Lock()
        self._stop_event = asyncio.Event()
        self._login_event: asyncio.Event | None = None
        self._pending_acks: dict[int, asyncio.Future] = {}
        self._connected_at = 0.0

    async def _async_update_data(self) -> AirVersaState:
        return self._state

    @property
    def state(self) -> AirVersaState:
        return self._state

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_start(self) -> None:
        self._stop_event.clear()
        create = getattr(self.hass, "async_create_background_task", None)
        if create is not None:
            self._connection_task = create(self._connection_loop(), "airversa_connection")
        else:
            self._connection_task = self.hass.loop.create_task(self._connection_loop())

    async def async_stop(self) -> None:
        self._stop_event.set()
        if self._connection_task:
            self._connection_task.cancel()
            try:
                await self._connection_task
            except (asyncio.CancelledError, Exception):
                pass
        await self._disconnect()

    # ------------------------------------------------------------------
    # Connection loop
    # ------------------------------------------------------------------

    async def _connection_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self._connect_and_run()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                _LOGGER.warning("AirVersa connection error: %s", exc)
            finally:
                await self._on_disconnect()

            if self._stop_event.is_set():
                break
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=RECONNECT_DELAY_S)
            except asyncio.TimeoutError:
                pass

    def _find_device(self) -> BLEDevice | None:
        """Freshest BLEDevice HA knows for this diffuser (adapter or proxy)."""
        if self.device_address:
            return bluetooth.async_ble_device_from_address(
                self.hass, self.device_address, connectable=True
            )
        for info in bluetooth.async_discovered_service_info(self.hass, connectable=True):
            if info.name == self.device_name:
                # Remember the address so retries can look it up directly
                self.device_address = info.address
                return info.device
        return None

    async def _connect_and_run(self) -> None:
        device = self._find_device()
        if device is None:
            _LOGGER.debug("AirVersa: '%s' not yet discovered, will retry", self.device_name)
            return

        _LOGGER.info("AirVersa: connecting to %s (%s)", device.name, device.address)
        # HA's recommended path: retries, proxy slot handling, GATT service caching
        client = await establish_connection(
            BleakClientWithServiceCache,
            device,
            self.device_name,
            disconnected_callback=self._on_ble_disconnect,
            ble_device_callback=lambda: self._find_device() or device,
        )
        self._connected_at = time.monotonic()
        try:
            self._client = client
            self._state.connected = True
            self._state.logged_in = False

            await client.start_notify(AK_CHAR_UUID, self._notification_handler)

            if not await self._login(client):
                if self.login_rejected:
                    # Retrying would just beep every few seconds; ask the user instead.
                    _LOGGER.error(
                        "AirVersa: activation code rejected — update it via the repair prompt"
                    )
                    self._stop_event.set()
                    if self.entry is not None:
                        self.entry.async_start_reauth(self.hass)
                else:
                    _LOGGER.error("AirVersa: login failed")
                return

            # Syncing the clock is what the app does after login; the device then
            # dumps its full state (limits, schedules, power, oil, ...).
            await self._write_bytes(self._time_sync_packet())
            _LOGGER.info("AirVersa: connected and logged in")

            last_keepalive = time.monotonic()
            while not self._stop_event.is_set() and client.is_connected:
                await asyncio.sleep(1.0)
                if time.monotonic() - last_keepalive >= KEEPALIVE_INTERVAL_S:
                    await self._write_bytes(KEEPALIVE_PACKET)
                    last_keepalive = time.monotonic()
                self._check_heartbeat_stale()
        finally:
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001
                pass

    async def _login(self, client: BleakClient) -> bool:
        packet = _login_packet(self.activation_key)
        self._login_event = asyncio.Event()
        await self._write_raw(client, packet)
        try:
            await asyncio.wait_for(self._login_event.wait(), timeout=LOGIN_TIMEOUT_S)
        except asyncio.TimeoutError:
            _LOGGER.warning("AirVersa: login timeout — no 0x8F response")
            return False
        finally:
            self._login_event = None
        return self._state.logged_in

    def _time_sync_packet(self) -> bytes:
        now = dt_util.now()
        return bytes(
            [
                CMD_TIME_SYNC,
                now.isoweekday() % 7,  # 0 = Sunday
                now.year % 100,
                now.month,
                now.day,
                now.hour,
                now.minute,
                now.second,
            ]
        )

    def _on_ble_disconnect(self, client: BleakClient) -> None:
        if self._stop_event.is_set():
            return
        uptime = time.monotonic() - self._connected_at if self._connected_at else 0
        _LOGGER.warning(
            "AirVersa: BLE disconnected from %s after %.0fs (logged in: %s)",
            client.address,
            uptime,
            self._state.logged_in,
        )
        self._connected_at = 0.0

    async def _on_disconnect(self) -> None:
        was_online = self._state.online
        self._state.connected = False
        self._state.logged_in = False
        self._client = None
        if was_online and not self._stop_event.is_set():
            self._state.grace_until = time.monotonic() + AVAILABILITY_GRACE_S
            self.hass.loop.call_later(AVAILABILITY_GRACE_S + 0.5, self._grace_expired)
        else:
            self._clear_heartbeat()
        for fut in self._pending_acks.values():
            if not fut.done():
                fut.cancel()
        self._pending_acks.clear()
        self._notify_state_change()

    async def _disconnect(self) -> None:
        client = self._client
        if client and client.is_connected:
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001
                pass
        self._client = None

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------

    def _notification_handler(self, sender, data: bytearray) -> None:
        if not data:
            return
        data = bytes(data)
        b0 = data[0]

        if b0 == PKT_WORKING_SCHED:
            self._handle_heartbeat(data)
            return
        _LOGGER.debug("AirVersa RX %s", data.hex())

        if b0 == PKT_LOGIN_RESULT:
            self._handle_login_result(data)
        elif b0 == PKT_SCHEDULE:
            self._handle_schedule(data)
        elif b0 == PKT_SET_COMPLETE:
            self._handle_set_complete(data)
        else:
            if b0 == PKT_TOTAL_CTRL and len(data) >= 2:
                self._state.powered_on = bool(data[1] & 0x01)
                self._notify_state_change()
            elif b0 == PKT_LIMITS and len(data) >= 8:
                self._state.diffuse_min = (data[2] << 8) | data[3]
                self._state.diffuse_max = (data[4] << 8) | data[5]
                self._state.pause_min = (data[6] << 8) | data[7]
                self._notify_state_change()
            elif b0 == PKT_DEVICE_MODEL:
                self._state.model = data[1:].decode("utf-8", errors="replace").strip("\x00")
            elif b0 == PKT_VERSION:
                self._state.version = data[1:17].decode("utf-8", errors="replace").strip("\x00")

            if b0 in ACK_ON_RECEIVE and self._state.logged_in:
                self._write_nowait(bytes([(b0 + ACK_MASK) & 0xFF]))

    @callback
    def _grace_expired(self) -> None:
        if not self._state.online:
            self._clear_heartbeat()
            self._notify_state_change()

    def _handle_login_result(self, data: bytes) -> None:
        if len(data) < 2:
            return
        version_str = data[1:min(12, len(data))].decode("utf-8", errors="replace")
        if _login_rejected(data):
            _LOGGER.error("AirVersa: login rejected (wrong activation code)")
            self._state.logged_in = False
            self.login_rejected = True
        else:
            self._state.logged_in = True
            self._state.grace_until = 0.0
            self._state.firmware = version_str
            if len(data) > 13 and not data[13] & 0x04:
                _LOGGER.warning(
                    "AirVersa: device does not report custom on/off support; "
                    "schedule writes may not work as expected"
                )
            _LOGGER.info("AirVersa: login OK, firmware=%s", version_str)

        if self._login_event:
            self._login_event.set()
        self._notify_state_change()

    def _handle_schedule(self, data: bytes) -> None:
        if len(data) < 14:
            return
        sched = Schedule.from_packet(data)
        if self._state.logged_in:
            self._write_nowait(bytes([CMD_SCHED_ACK, sched.aroma, sched.index]))
        if 1 <= sched.index <= NUM_SCHEDULES:
            self._state.schedules[sched.index] = sched
            self._notify_state_change()

    def _handle_set_complete(self, data: bytes) -> None:
        index = data[2] if len(data) >= 3 else None
        fut = self._pending_acks.pop(index, None) if index is not None else None
        if fut is None and self._pending_acks:
            # Fall back to the oldest pending write
            _, fut = self._pending_acks.popitem()
        if fut and not fut.done():
            fut.set_result(True)

    def _handle_heartbeat(self, data: bytes) -> None:
        """0x59: [0x59, 0x01, status, diffuse_remaining(2), pause_remaining(2)].

        status & 0x07 = running schedule slot (0 = idle), status & 0x08 = diffusing.
        While a schedule runs, the counter for the current phase ticks down 1/s.
        """
        if len(data) < 7 or data[1] != 0x01:
            return
        s = self._state
        status = data[2]
        s.active_slot = status & 0x07
        s.is_diffusing = bool(status & 0x08)
        s.last_heartbeat = time.monotonic()

        if s.active_slot == 0 or not s.powered_on:
            self._clear_heartbeat(keep_slot=True)
            self._notify_state_change()
            return

        diffuse_rem = (data[3] << 8) | data[4]
        pause_rem = (data[5] << 8) | data[6]
        remaining = diffuse_rem if s.is_diffusing else pause_rem
        s.phase_remaining = remaining

        now = dt_util.utcnow()
        phase_ends = now + timedelta(seconds=remaining)
        if s.is_diffusing:
            sched = s.schedules.get(s.active_slot)
            next_burst = phase_ends + timedelta(seconds=sched.off_time if sched else 0)
        else:
            next_burst = phase_ends

        s.phase_ends = self._stable_ts(s.phase_ends, phase_ends)
        s.next_burst = self._stable_ts(s.next_burst, next_burst)
        self._notify_state_change()

    @staticmethod
    def _stable_ts(old: datetime | None, new: datetime) -> datetime:
        if old is not None and abs((new - old).total_seconds()) < TIMESTAMP_JITTER_S:
            return old
        return new.replace(microsecond=0)

    def _clear_heartbeat(self, keep_slot: bool = False) -> None:
        s = self._state
        if not keep_slot:
            s.active_slot = 0
            s.is_diffusing = False
        s.phase_remaining = None
        s.phase_ends = None
        s.next_burst = None

    def _check_heartbeat_stale(self) -> None:
        s = self._state
        if s.active_slot and time.monotonic() - s.last_heartbeat > HEARTBEAT_STALE_S:
            self._clear_heartbeat()
            self._notify_state_change()

    @callback
    def _notify_state_change(self) -> None:
        self.async_set_updated_data(self._state)

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    def _require_online(self) -> None:
        if not self._state.online:
            raise HomeAssistantError("AirVersa is reconnecting — try again in a few seconds")

    @staticmethod
    def _total_ctrl_packet(on: bool) -> bytes:
        # Note: the app's 0x40 "mute" bit is dead code (never exposed in its UI);
        # on the ANW, any 0x2D 'on' just restarts the schedule cycle with a beep.
        return bytes([CMD_TOTAL_CTRL, CTRL_ON if on else CTRL_OFF])

    async def async_set_power(self, on: bool) -> None:
        """Master enable — schedules only run while this is on."""
        self._require_online()
        await self._write_bytes(self._total_ctrl_packet(on))
        await asyncio.sleep(0.1)
        await self._write_bytes(bytes([CMD_SCHEDULE, 0x01, 0x02, FAN_ON_VAL if on else FAN_OFF_VAL]))
        self._state.powered_on = on
        if not on:
            self._clear_heartbeat()
        self._notify_state_change()

    async def async_update_schedule(self, index: int, **changes) -> None:
        """Change fields of schedule `index` and write it to the device.

        Accepted keys: enabled, start, end, days (int mask or list of day names),
        on_time, off_time (seconds).
        """
        s = self._state
        self._require_online()
        current = s.schedules.get(index)
        if current is None:
            raise HomeAssistantError(f"Schedule {index} has not been read from the device yet")

        sched = dataclasses.replace(current)
        if "days" in changes and not isinstance(changes["days"], int):
            mask = 0
            for d in changes["days"]:
                mask |= 1 << DAY_BITS[d]
            changes["days"] = mask

        for key, value in changes.items():
            if value is not None:
                setattr(sched, key, value)

        if not current.shown:
            if changes == {"enabled": False}:
                return  # turning off an empty slot is a no-op
            # Any other change to an empty slot creates a schedule there
            sched.shown = True
            sched.fan = True  # app default for new schedules
            if "start" not in changes and "end" not in changes:
                sched.start = sched.end = dt_time(0, 0)  # all day
            if "days" not in changes:
                sched.days = 0x7F

        # ANW has no grade mode; the app forces custom on/off mode on every save
        sched.work_mode = 1
        sched.on_time = max(s.diffuse_min, min(s.diffuse_max, int(sched.on_time)))
        sched.off_time = max(s.pause_min, min(s.pause_max, int(sched.off_time)))
        if sched.days == 0:
            raise HomeAssistantError("A schedule needs at least one day")

        await self._write_schedule(sched)

    async def _write_schedule(self, sched: Schedule) -> None:
        packet = sched.to_packet()
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self._pending_acks[sched.index] = fut
        _LOGGER.debug("AirVersa TX schedule %s", packet.hex())
        await self._write_bytes(packet)
        try:
            await asyncio.wait_for(fut, timeout=WRITE_ACK_TIMEOUT_S)
        except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
            self._pending_acks.pop(sched.index, None)
            raise HomeAssistantError(
                f"AirVersa did not confirm the write to schedule {sched.index}"
            ) from exc
        self._state.schedules[sched.index] = sched
        self._notify_state_change()

    # ------------------------------------------------------------------
    # Low-level writes
    # ------------------------------------------------------------------

    def _write_nowait(self, data: bytes) -> None:
        self.hass.async_create_task(self._write_bytes(data))

    async def _write_bytes(self, data: bytes) -> None:
        async with self._write_lock:
            client = self._client
            if not client or not client.is_connected:
                _LOGGER.debug("AirVersa: write ignored — not connected")
                return
            await self._write_raw(client, data)

    @staticmethod
    async def _write_raw(client: BleakClient, data: bytes) -> None:
        try:
            await client.write_gatt_char(AK_CHAR_UUID, data, response=False)
        except BleakError as exc:
            _LOGGER.warning("AirVersa: write error: %s", exc)
