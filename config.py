from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


CONFIG_PATH = Path.home() / ".powerstack" / "config.json"


@dataclass
class RemoteConfig:
    host: str = ""
    user: str = ""
    port: int = 22
    ssh_key_path: str = ""
    suspend_command: str = "systemctl suspend"


@dataclass
class RelayConfig:
    gpio_pin: int = 4
    active_high: bool = True
    pulse_seconds: float = 0.5
    holdoff_seconds: float = 0.2


@dataclass
class ScheduleEvent:
    id: str
    label: str
    action: str  # "suspend" or "wake"
    time_hhmm: str
    recurrence: str = "weekly"  # "weekly" or "once"
    date_ymd: str = ""  # YYYY-MM-DD when recurrence == "once"
    weekdays: list[int] = field(default_factory=lambda: list(range(7)))  # 0=Mon
    enabled: bool = True


@dataclass
class AppConfig:
    remote: RemoteConfig = field(default_factory=RemoteConfig)
    relay: RelayConfig = field(default_factory=RelayConfig)
    schedule: list[ScheduleEvent] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> "AppConfig":
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            cfg = cls()
            cfg.save(path)
            return cfg
        raw = json.loads(path.read_text())
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "AppConfig":
        remote = RemoteConfig(**raw.get("remote", {}))
        relay = RelayConfig(**raw.get("relay", {}))
        schedule = [ScheduleEvent(**e) for e in raw.get("schedule", [])]
        return cls(remote=remote, relay=relay, schedule=schedule)

    def save(self, path: Path = CONFIG_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2))
