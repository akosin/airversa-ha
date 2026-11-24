# AirVersa for Home Assistant

[![HACS Default](https://img.shields.io/badge/HACS-Default-41BDF5.svg)](https://hacs.xyz/)
[![Validate](https://github.com/akosin/airversa-ha/actions/workflows/validate.yml/badge.svg)](https://github.com/akosin/airversa-ha/actions/workflows/validate.yml)

Local Bluetooth control of **AirVersa** scent diffusers (tested with the **Scenta XL**, other models [likely work](#supported-devices)) from Home Assistant. No Sleekpoint app and no cloud.

- Master power switch
- Up to 5 schedules, each with an active window, days of the week, burst length and pause between bursts
- Live countdown to the next burst, the current phase (diffusing / paused / idle), and which schedule is running
- Discovered automatically over Bluetooth

> This is an unofficial, community project. It isn't affiliated with or endorsed by AirVersa or Sleekpoint.

## Supported devices

These diffusers use the same Bluetooth protocol, so all of them are auto-discovered:

| Bluetooth name | Model | Status |
|---|---|---|
| `SP_…`, `A32…` | Scenta XL (ANW) | ✅ Tested: everything works |
| `SP3…` | Scenta (RDX) | 🟡 Should work, untested. Please report back! |
| `SP1…`, `SP2…` | ANP / ANA models | 🟡 Should work, untested |
| `SP4…` | U1 | ❌ Uses a different protocol, not supported |

On untested models, power and the countdown sensors should work. The schedule format may differ. If the device doesn't report support for custom schedules, the integration logs a warning. Please [open an issue](https://github.com/akosin/airversa-ha/issues) with your results.

## Requirements

- Home Assistant with working [Bluetooth](https://www.home-assistant.io/integrations/bluetooth/): a local adapter or an [ESPHome Bluetooth proxy](https://esphome.io/components/bluetooth_proxy.html) within range of the diffuser.
- The diffuser's 4-digit **activation code**. The factory default is **8888**. If you changed it in the Sleekpoint app, use that code instead.
- Home Assistant **2026.3 or newer** to show the AirVersa logo. Older versions work but show a placeholder icon.

## Installation

### HACS (recommended)

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=akosin&repository=airversa-ha&category=integration)

1. In HACS, search for **AirVersa** and open it. The button above also takes you straight there.
2. Click **Download**.
3. Restart Home Assistant.

<details>
<summary>AirVersa doesn't show up in HACS?</summary>

Add it as a custom repository: in HACS, open the ⋮ menu → **Custom repositories**, add `https://github.com/akosin/airversa-ha` with type **Integration**, then search again.

</details>

### Manual

Copy `custom_components/airversa/` into your Home Assistant `config/custom_components/` folder and restart.

## Setup

1. **Close the Sleekpoint app** on your phone, or turn off the phone's Bluetooth. The diffuser accepts only one Bluetooth connection at a time.
2. Home Assistant should show a **Discovered: AirVersa** card under **Settings → Devices & services**. Click **Add**. If no card appears, use **Add integration → AirVersa** and pick your diffuser from the list.
3. Enter the activation code (default `8888`). The diffuser beeps once while the code is checked.

If the code is changed later, Home Assistant shows a **Reconfigure** prompt asking for the new one.

## Entities

| Entity | Type | Notes |
|---|---|---|
| Power | Switch | Master enable. Schedules only run while this is on. Turning it on restarts the current cycle, so it beeps and starts a burst. |
| Schedule 1 – 5 | Switch | Turns each schedule on or off. Attributes: start, end, days, diffuse/pause seconds, `configured`, `running`. |
| Schedule N diffuse | Number (s) | Burst length (device limit 3–300 s). |
| Schedule N pause | Number (min) | Time between bursts. |
| Schedule N start / end | Time | Active window. **Start = end means all day.** |
| Active schedule | Sensor | Which schedule is running right now. |
| Phase | Sensor | `diffusing`, `paused` or `idle`. |
| Phase time remaining | Sensor (s) | Live countdown of the current phase. |
| Next burst | Sensor (timestamp) | When the next burst starts. Dashboards show it as "in 3 minutes". |

Turning on an empty schedule slot, or setting any of its values, creates a schedule there that runs all day, every day.

### `airversa.set_schedule` action

Sets several schedule fields at once, including the days of the week, which don't have their own entity. Target a **Schedule N** switch:

```yaml
action: airversa.set_schedule
target:
  entity_id: switch.airversa_1a2b_schedule_3
data:
  enabled: true
  start: "08:00"
  end: "22:00"
  days: [mon, tue, wed, thu, fri]
  diffuse_seconds: 30
  pause_seconds: 240
```

### Keeping the countdown out of history

`Phase time remaining` changes every second. To keep it out of the recorder:

```yaml
recorder:
  exclude:
    entity_globs:
      - sensor.*_phase_time_remaining
```

## Troubleshooting

- **The diffuser beeps when Home Assistant connects.** That's the device's built-in connect beep, and there's no command to turn it off. The integration keeps one connection open, so you should only hear it when Home Assistant starts or after the diffuser has been out of range.
- **Entities are unavailable.** Check that the Sleekpoint app isn't connected, and that the diffuser appears under **Settings → Devices & services → Bluetooth → Advertisement monitor** with a reasonable signal (better than about −90 dBm).
- **Debug logs:**

  ```yaml
  logger:
    logs:
      custom_components.airversa: debug
  ```

## How it works

The diffuser speaks a simple byte protocol over one BLE characteristic. [docs/PROTOCOL.md](docs/PROTOCOL.md) documents everything this integration uses, including login, schedules, the heartbeat countdown and the keep-alive.

## License

[MIT](LICENSE). AirVersa and its logo are trademarks of their owner and appear here only to identify the compatible device.
