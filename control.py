from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from config import RelayConfig, RemoteConfig


LogFn = Callable[[str], None]


try:
    from gpiozero import OutputDevice  # type: ignore
except Exception:  # pragma: no cover - dev environments without GPIO
    OutputDevice = None


class RelayController:
    def __init__(self, config: RelayConfig, log: LogFn):
        self.config = config
        self.log = log
        self._lock = threading.Lock()
        self._device = None
        self._mock = False
        self._setup_device()

    def _setup_device(self) -> None:
        if OutputDevice is None:
            self._mock = True
            self.log("GPIO library not available, relay running in mock mode.")
            return
        try:
            self._device = OutputDevice(
                pin=self.config.gpio_pin,
                active_high=self.config.active_high,
                initial_value=False,
            )
            self.log(f"Relay ready on GPIO {self.config.gpio_pin}.")
        except Exception as exc:
            self._mock = True
            self.log(f"Relay init failed, using mock mode: {exc}")

    def reconfigure(self, config: RelayConfig) -> None:
        self.config = config
        if self._device is not None:
            try:
                self._device.close()
            except Exception:
                pass
        self._device = None
        self._mock = False
        self._setup_device()

    def pulse(self, on_seconds: float, label: str = "relay pulse") -> None:
        with self._lock:
            self.log(
                f"{label}: pulsing relay (GPIO {self.config.gpio_pin}) for {on_seconds:.2f}s."
            )
            if self._mock or self._device is None:
                time.sleep(on_seconds)
                time.sleep(self.config.holdoff_seconds)
                self.log(f"Mock {label} complete.")
                return
            self._device.on()
            time.sleep(on_seconds)
            self._device.off()
            time.sleep(self.config.holdoff_seconds)
            self.log(f"{label} complete.")


@dataclass
class CommandResult:
    ok: bool
    message: str


class RemotePcController:
    def __init__(self, relay: RelayController, log: LogFn):
        self.relay = relay
        self.log = log

    def suspend(self, config: RemoteConfig) -> CommandResult:
        if not config.host or not config.user:
            return CommandResult(False, "Remote host/user is not configured.")
        cmd = [
            "ssh",
            "-p",
            str(config.port),
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
        ]
        if config.ssh_key_path:
            cmd.extend(["-i", str(Path(config.ssh_key_path).expanduser())])
        target = f"{config.user}@{config.host}"
        cmd.append(target)
        cmd.append(config.suspend_command)
        self.log(f"Running remote suspend command on {target}.")
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
        except Exception as exc:
            return CommandResult(False, f"SSH failed: {exc}")
        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip()
            stdout = (proc.stdout or "").strip()
            detail = stderr or stdout or f"Exit code {proc.returncode}"
            return CommandResult(False, f"Suspend command failed: {detail}")
        return CommandResult(True, "Suspend command sent successfully.")

    def wake_via_power_button(self, on_seconds: float) -> CommandResult:
        try:
            self.relay.pulse(on_seconds=on_seconds, label="Wake action")
            return CommandResult(True, "Power button relay pulse sent.")
        except Exception as exc:
            return CommandResult(False, f"Relay pulse failed: {exc}")

    def toggle_power(self, on_seconds: float) -> CommandResult:
        try:
            self.relay.pulse(on_seconds=on_seconds, label="Toggle power action")
            return CommandResult(True, "Power toggle relay pulse sent.")
        except Exception as exc:
            return CommandResult(False, f"Relay toggle failed: {exc}")


def run_async(fn: Callable[[], CommandResult], log: LogFn) -> None:
    def _worker() -> None:
        result = fn()
        level = "OK" if result.ok else "ERROR"
        log(f"[{level}] {result.message}")

    threading.Thread(target=_worker, daemon=True).start()
