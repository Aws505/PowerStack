# PowerStack

PowerStack is a Raspberry Pi 4 controller for managing the power state of a remote Ubuntu PC via SSH and a relay HAT.

It provides both a **Tkinter GUI** and a **CLI** — both backed by **system cron** for scheduling.

## Features

- Remote suspend over SSH
- Wake / power-button pulse through a relay HAT
- Dedicated power-toggle relay action
- Weekly and one-time schedule events managed through system `crontab`
- Schedule overview with status colour coding:
  - `Enabled` (green)
  - `Paused` (amber)
  - `Completed` (gray — one-time events after execution)
- Per-event controls: Start, Pause, Run Now, Remove
- One-time events auto-disable after cron fires them

## Scheduling (system cron)

PowerStack writes a dedicated block to the user's crontab, delimited by markers:

```
# BEGIN POWERSTACK
30 22 * * 1,2,3,4,5  /usr/bin/python3 /path/to/cli.py _run <event-id>  # Nightly Suspend
# END POWERSTACK
```

Existing crontab entries outside this block are never touched.
Both the GUI and CLI sync the crontab automatically whenever events are saved.

## GUI Usage

```bash
python3 app.py
```

Open the GUI dashboard. Use **Refresh** to reload the schedule from disk (e.g. after a CLI edit).

### GUI windows

| Button | Purpose |
|--------|---------|
| Suspend Config | SSH / relay / timing settings |
| Schedule Config | Add new schedule events |
| Logs | Full session log |
| Refresh | Reload config + re-sync crontab |

## CLI Usage

```bash
python3 app.py <command> [options]
```

All CLI commands are also available as `python3 cli.py <command>`.

### Commands

| Command | Description |
|---------|-------------|
| `list` | List all scheduled events |
| `next` | Show next 10 upcoming events |
| `trigger <event>` | Manually run an event's action |
| `add --time HH:MM ...` | Add a scheduled event |
| `remove <event>` | Remove an event |
| `enable <event>` | Enable a paused event |
| `disable <event>` | Pause an active event |
| `suspend` | Suspend the remote PC immediately |
| `wake` | Wake the remote PC immediately |
| `toggle` | Toggle the remote PC power immediately |

`<event>` can be a **1-based list index**, an **event ID (UUID)**, or a **label** (case-insensitive).

### Examples

```bash
# View schedule
python3 app.py list
python3 app.py next

# Add a weekly suspend Mon–Fri at 22:30
python3 app.py add --time 22:30 --action suspend --label "Nightly Suspend" --days mon,tue,wed,thu,fri

# Add a one-time wake
python3 app.py add --time 08:00 --action wake --recurrence once --date 2026-06-01

# Control events
python3 app.py disable 1
python3 app.py enable "Nightly Suspend"
python3 app.py trigger 2
python3 app.py remove 3

# Immediate actions
python3 app.py suspend
python3 app.py wake
python3 app.py toggle
```

### `add` options

| Flag | Short | Description |
|------|-------|-------------|
| `--time HH:MM` | `-t` | Time in 24-hour format (required) |
| `--action` | `-a` | `suspend` / `wake` / `toggle` (default: `suspend`) |
| `--label` | `-l` | Human-readable name |
| `--recurrence` | `-r` | `weekly` (default) or `once` |
| `--days` | `-d` | Weekdays: `mon,tue,…` or `0-6` (0=Mon). Default: all |
| `--date` | | Date for once events: `YYYY-MM-DD` |
| `--disabled` | | Create the event in a disabled state |

## Hardware Notes (KEYESTUDIO KS0212)

This project supports configurable relay settings and includes defaults for the Keyestudio `KS0212` (4-channel relay HAT).

Common BCM mapping:

| Channel | BCM Pin |
|---------|---------|
| Relay 1 | 4 |
| Relay 2 | 22 |
| Relay 3 | 6 |
| Relay 4 | 26 |

Default relay settings:

| Setting | Default |
|---------|---------|
| GPIO Pin | 4 |
| Relay Active High | true |
| Wake Mode | `pulse` |
| Wake On Time | 0.5 s |
| Toggle On Time | 1.5 s |

If your board revision differs, change the pin/polarity in `Suspend Config` (GUI) or edit `~/.powerstack/config.json`.

## Installation

### 1. System packages

```bash
sudo apt update
sudo apt install -y python3 python3-tk python3-pip openssh-client
```

### 2. Python dependencies

```bash
pip3 install -r requirements.txt
```

### 3. SSH setup (Pi → Ubuntu PC)

```bash
ssh-keygen -t ed25519
ssh-copy-id user@ubuntu-pc
```

Ensure the remote user can run the suspend command (default: `systemctl suspend`).

### 4. Relay wiring

Wire one relay channel's NO/COM contacts in parallel with the target PC's motherboard power-button header pins.

## Configuration

Configuration is stored at:

```
~/.powerstack/config.json
```

Cron log output is appended to:

```
~/.powerstack/powerstack.log
```

## Safety

- A power-button pulse can shut down, suspend, or wake a PC depending on BIOS/OS settings.
- Start with short pulses (`0.3`–`0.5 s`) and test carefully.
- Validate relay polarity (`active high` / `active low`) before production use.

## License

This project is licensed under the MIT License. See `LICENSE`.

## Recent Updates

- **Replaced in-app scheduler with system cron**: schedule events now live in the user's crontab, surviving reboots and independent of the GUI process.
- **Added CLI** (`cli.py` / `python3 app.py <command>`): full parity with GUI for listing, adding, editing, triggering, enabling/disabling, and removing events.
- **Added Refresh button** to GUI to reload config and re-sync crontab from disk.
- **Cron log**: cron-triggered actions are logged to `~/.powerstack/powerstack.log`.
- Added separate relay on-time settings for wake and toggle behavior.
- Added configurable `Wake Mode`: `pulse` or `toggle`.
- Added `toggle` as a schedule action type.
