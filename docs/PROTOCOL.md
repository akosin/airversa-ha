# AirVersa BLE protocol

Reverse-engineered from the Sleekpoint Android app (1.0.87, "AK" protocol family) and verified live against a Scenta XL (model `ANW`, firmware `CY_V3.0`). Name prefix → model (`AppHelper.getModelFromBLEDeviceName`): `SP_`/`A32` = ANW, `SP1` = ANP, `SP2` = ANA, `SP3` = RDX, `SP4` = U1. U1 uses the separate "GW" protocol (different service/characteristics); the rest use this one. Only ANW has been verified. A third-party integration confirms the same login (`8F "8888OK01"`), keep-alive and `2D 13/12` power commands on an `SP3M…` (RDX).

## Transport

| Layer | Value |
|-------|-------|
| BLE service | `0000fff0-0000-1000-8000-00805f9b34fb` |
| Data characteristic (R/W/Notify) | `0000fff6-0000-1000-8000-00805f9b34fb`, always write-without-response |

## Session

1. **Login** → `8F` + `"<code>OK01"` (e.g. `"8888OK01"` for the factory code) → device replies `8F "CY_V3.0OK01" 01 55 C2` (wrong code: `8F "ERROR"`)
   - byte 13 `0x55`: bit2 = *custom on/off times* supported (18-byte schedules)
   - byte 14 `0xC2`: bit7 = *reply* (device expects ACKs)
2. **Time sync** → `21 [weekday 0=Sun] [yy] [MM] [dd] [HH] [mm] [ss]` (plain decimal values). This triggers the full state dump:
   `46` limits, `42` name, `45` model `"ANW"`, `4A`×5 schedules, `43` label/refill, `47` grade table, `48` oil names, `4B`, `44` versions, `4D` power, `4C`, `4E`, `50` oil
3. **ACKs**: most packets → `[b0 + 0x80]`. Schedule packets `4A` → **`CA [aroma] [index]`**.
4. **Heartbeat** `59` arrives ~1/s.
5. **Keep-alive**: app → `E0 AA 55` every 5 s. Without it the device drops the connection, and it beeps on every reconnect.

## Schedules (`0x4A` in, `0x2A` out)

```
idx: 0  1     2  3      4  5     6     7   8   9    10   11     12   13    14-15  16-17
     4A aroma 02 fogfan wt index flags hOn mOn hOff mOff repeat mode grade onSec  offSec
```
- `flags`: bit0 = exists (shown), bit1 = enabled, bit2 = fan
- `repeat`: bit0 = Sunday … bit6 = Saturday (`7F` = every day)
- `hOn:mOn == hOff:mOff` → all day
- Write = same layout with byte0 `2A`, byte3 `01 | fan<<1`, byte4 `00`, `mode` = 1. Device ACKs `AA [aroma] [index]` and keeps the value (verified by reconnect read-back).
- 5 slots max.

## Heartbeat (`0x59`) = live countdown

`59 01 [status] [diffuse_remaining:2] [pause_remaining:2]`
- `status & 0x07` = running slot (0 = idle), `status & 0x08` = diffusing now
- The counter for the current phase counts down in seconds, e.g. `590102000000a1` = slot 2, paused, 161 s until the next burst.

## Other

| Packet | Meaning |
|---|---|
| `2D 13` / `2D 12` | Master enable on/off (reply `AD`) |
| `4D xx` | Master enable = `xx & 0x01`, bit6 = app's unused mute flag |
| `2D 53` | "Mute" bit `0x40`: dead code in the app. On ANW it just acts as power-on (restarts the cycle with a beep). Don't use. |
| `46 [maxGrade] [onMin:2] [onMax:2] [offMin:2] …` | Limits: on 3–300 s, off ≥ 5 s |
| `2A 01 02 03/01` | 4-byte form: global fan on/off (sent with power) |

## Ideas / not implemented

- Refill tracking (`0x43` label/last fill, `0x4B`/`0x50` oil totals)
- Countdown timer mode (`ScentTimerModel`, `0x3C` 16-byte). The ANW schedules screen doesn't use it.
- Changing the activation code (`0x0F`)

## Debugging without Home Assistant

Any `bleak` script can talk to the device. It needs to log in, send the time sync, ACK what's listed above, and send the keep-alive every 5 s. On macOS, use a Python whose PyObjC works with bleak (3.11 worked; one 3.13 install failed with "unknown slot ID 4").
