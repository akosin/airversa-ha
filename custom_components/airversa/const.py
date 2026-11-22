"""AirVersa Scenta XL constants."""
DOMAIN = "airversa"

# BLE characteristics (AK protocol)
AK_CHAR_UUID = "0000fff6-0000-1000-8000-00805f9b34fb"
AK_SERVICE_UUID = "0000fff0-0000-1000-8000-00805f9b34fb"

# Hardcoded pair code (from DeviceInfoModel static constructor)
PAIR_CODE = "OK01"

# ---------------------------------------------------------------------------
# Outgoing commands (write to fff6, write-without-response)
# ---------------------------------------------------------------------------
CMD_LOGIN      = 0x8F  # [0x8F] + (key + PAIR_CODE).encode()
CMD_TIME_SYNC  = 0x21  # [0x21, weekday(0=Sun), yy, MM, dd, HH, mm, ss] — triggers full data dump
CMD_TOTAL_CTRL = 0x2D  # [0x2D, 0x13=on / 0x12=off]  (master enable)
CMD_SCHEDULE   = 0x2A  # 18-byte schedule write (see Schedule.to_packet); 4-byte form = fan state
CMD_SCHED_ACK  = 0xCA  # [0xCA, aroma, index] — ACK for each incoming 0x4A schedule packet

CTRL_ON   = 0x13
CTRL_OFF  = 0x12

# App sends this every 5 s on AK devices (BluetoothManager.connectionState timer)
KEEPALIVE_PACKET = bytes([0xE0, 0xAA, 0x55])
KEEPALIVE_INTERVAL_S = 5.0

FAN_ON_VAL  = 0x03
FAN_OFF_VAL = 0x01

# ---------------------------------------------------------------------------
# Incoming packets
# ---------------------------------------------------------------------------
PKT_LOGIN_RESULT  = 0x8F  # login result + capability flags
PKT_WORKING_SCHED = 0x59  # heartbeat ~1/s: active slot, phase, live countdown
PKT_SCHEDULE      = 0x4A  # one per schedule slot (sent after time sync)
PKT_TOTAL_CTRL    = 0x4D  # master enable state: byte1 bit0
PKT_LIMITS        = 0x46  # maxGrade, diffuse min/max, pause min (seconds)
PKT_DEVICE_MODEL  = 0x45  # e.g. "ANW"
PKT_VERSION       = 0x44  # PCB / firmware version strings
PKT_SET_COMPLETE  = 0xAA  # write ACK: [0xAA, aroma, index]

ACK_MASK = 0x80

# Packets the app ACKs with [byte0 + 0x80] (BtDataModel.sendAck). 0x4A has its own ACK.
ACK_ON_RECEIVE = {
    0x41, 0x42, 0x43, 0x44, 0x45, 0x46, 0x47, 0x48, 0x4B, 0x4C, 0x4D, 0x4E,
    0x50, 0x51, 0x55, 0x56, 0x5A, 0x5B, 0x5C, 0x5D, 0x5E, 0x5F, 0x60, 0x61, 0x62,
}

# ---------------------------------------------------------------------------
# Schedules
# ---------------------------------------------------------------------------
NUM_SCHEDULES = 5  # app hides "add" once 5 exist

# Repeat bitmask: bit0 = Sunday … bit6 = Saturday
DAY_BITS = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}
DAY_ORDER = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

# Fallback limits (seconds) until the device's 0x46 packet arrives
DEFAULT_DIFFUSE_MIN = 3
DEFAULT_DIFFUSE_MAX = 300
DEFAULT_PAUSE_MIN = 5
PAUSE_MAX = 3600  # app's hardcoded customOffMax

# Config entry keys
CONF_ADDRESS    = "address"
CONF_NAME       = "name"
CONF_KEY        = "key"

# Factory activation code (shown in the Sleekpoint app's activation screen)
DEFAULT_KEY = "8888"

# BLE local-name prefixes of Sleekpoint "AK" protocol devices (AppHelper.getModelFromBLEDeviceName).
# Keep in sync with manifest.json. SP4 ("U1") uses the different GW protocol and is excluded.
NAME_PREFIXES: tuple[str, ...] = ("SP_", "A32", "SP1", "SP2", "SP3")

# Prefix -> (model code, product name). Only ANW is verified with this integration.
MODEL_BY_PREFIX: dict[str, tuple[str, str]] = {
    "SP_": ("ANW", "Scenta XL"),
    "A32": ("ANW", "Scenta XL"),
    "SP1": ("ANP", "AirVersa diffuser (ANP)"),
    "SP2": ("ANA", "AirVersa diffuser (ANA)"),
    "SP3": ("RDX", "Scenta"),
}


def model_for_name(name: str | None) -> tuple[str, str] | None:
    for prefix, model in MODEL_BY_PREFIX.items():
        if name and name.startswith(prefix):
            return model
    return None
