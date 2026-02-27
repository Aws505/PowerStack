# PowerStack Pi Controller

Tkinter GUI app for a Raspberry Pi 4 that can:

- Send a remote `suspend` command to an Ubuntu PC over SSH
- Pulse a relay (wired across the PC power switch header) to wake/power-toggle the PC
- Schedule `suspend` and `wake` events at specific times (weekly or one-time dates)
- Run a selected schedule event immediately for testing

## GUI layout

The app now uses a modular window layout:

- Main window:
  - Schedule overview table with color-coded status
  - `Suspend Now` / `Wake Now`
  - Per-item `Start Selected` / `Pause Selected` / `Run Selected Now`
  - Buttons to open the 3 dedicated windows
- `Suspend Config` window:
  - Remote SSH suspend settings
  - Relay channel/pin/pulse settings
  - `Test Relay` and `Save`
- `Schedule Configuration` window:
  - Full schedule editor (add/update/delete, weekly or one-time)
- `Logs` window:
  - Full runtime logs

## Notes about the relay HAT (KEYESTUDIO KS0212)

The Amazon short link provided (`https://a.co/d/02SlqwPX`) returned `404`, but the model `KEYESTUDIO KS0212` is documented on the Keyestudio wiki.

For KS0212, the wiki sample maps the 4 relay channels to Raspberry Pi BCM GPIO pins:

- Relay 1 -> `BCM 4`
- Relay 2 -> `BCM 22`
- Relay 3 -> `BCM 6`
- Relay 4 -> `BCM 26`

The sample code indicates relay activation is `HIGH` (active-high), and this app defaults to:

- `GPIO Pin = 4` (Relay 1)
- `Relay Active High = true`

The app still exposes relay settings in the UI so you can choose a different channel/polarity if your board revision/jumper configuration differs:

- `GPIO Pin`
- `Relay Active High`
- `Pulse (s)`

Use the `Test Relay` button to pulse the relay using the current relay form values without saving them.

Set these to match your HAT's channel input and trigger logic.

## Raspberry Pi setup (Ubuntu or Raspberry Pi OS)

1. Install packages:

```bash
sudo apt update
sudo apt install -y python3 python3-tk python3-pip openssh-client
pip3 install -r requirements.txt
```

2. Enable GPIO access (on Raspberry Pi OS, typically available by default; otherwise ensure your user can access GPIO).

3. Wire the relay output contacts in parallel with the PC's physical power button pins on the motherboard front-panel header.

4. Set up SSH key-based access from the Pi to the Ubuntu PC:

```bash
ssh-keygen -t ed25519
ssh-copy-id user@ubuntu-pc
```

5. On the Ubuntu PC, allow suspend via `systemctl suspend` for the SSH user (this depends on your policy/polkit setup).

## Run

```bash
python3 app.py
```

Config is stored at `~/.powerstack/config.json`.

## Safety and behavior

- `wake` uses a relay pulse to emulate a power button press.
- If the PC is already running, a power-button pulse may trigger shutdown/suspend depending on Ubuntu power-button settings.
- Test with a short pulse (for example `0.3`-`0.5` seconds).
- One-time schedule events match a specific `YYYY-MM-DD` date plus time.
- One-time schedule events are auto-disabled after they fire once.
- Status coloring in schedule tables:
  - `Enabled` = green
  - `Paused` = amber
  - `Completed` = gray (one-time events that have run)
