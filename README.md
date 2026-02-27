# PowerStack

PowerStack is a Raspberry Pi 4 desktop app for controlling the power state of a remote Ubuntu PC.

It provides:

- Remote suspend over SSH
- Wake/power-button pulse through a relay HAT
- Weekly and one-time schedule events
- A modular Tkinter GUI with separate windows for:
  - suspend/relay configuration
  - schedule event creation
  - logs

## Features

- `Suspend Now` and `Wake Now` actions from the main dashboard
- Schedule overview with status color coding:
  - `Enabled` (green)
  - `Paused` (amber)
  - `Completed` (gray; one-time events after execution)
- Per-item controls on selected events:
  - `Start`
  - `Pause`
  - `Run Now`
  - `Remove Event`
- Add-only schedule form window (`Schedule Config`)
- One-time events auto-disable after firing once

## Hardware Notes (KEYESTUDIO KS0212)

This project supports configurable relay settings and includes defaults for Keyestudio `KS0212` (4-channel relay HAT).

Common BCM mapping:

- Relay 1 -> `BCM 4`
- Relay 2 -> `BCM 22`
- Relay 3 -> `BCM 6`
- Relay 4 -> `BCM 26`

Default app relay settings:

- `GPIO Pin = 4`
- `Relay Active High = true`

If your board revision differs, change the pin/polarity in `Suspend Config`.

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

### 3. SSH setup (Pi -> Ubuntu PC)

```bash
ssh-keygen -t ed25519
ssh-copy-id user@ubuntu-pc
```

Ensure the remote user can run your suspend command (default: `systemctl suspend`).

### 4. Relay wiring

Wire one relay channel contacts in parallel with the target PC motherboard power-button pins.

## Usage

Run:

```bash
python3 app.py
```

Configuration is stored at:

`~/.powerstack/config.json`

## Safety

- A power-button pulse can shut down, suspend, or wake a PC depending on BIOS/OS power-button behavior.
- Start with short pulses (`0.3` to `0.5` seconds) and test carefully.
- Validate relay polarity (`active high` / `active low`) before production use.

## License

This project is licensed under the MIT License. See `LICENSE`.
