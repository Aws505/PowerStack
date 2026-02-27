from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Callable

from config import ScheduleEvent


ActionFn = Callable[[ScheduleEvent], None]
LogFn = Callable[[str], None]


class EventScheduler:
    def __init__(self, log: LogFn, action_runner: ActionFn):
        self.log = log
        self.action_runner = action_runner
        self._events: list[ScheduleEvent] = []
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._last_fired: set[str] = set()
        self._lock = threading.Lock()

    def set_events(self, events: list[ScheduleEvent]) -> None:
        with self._lock:
            self._events = list(events)
        self.log(f"Scheduler loaded {len(events)} event(s).")

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self.log("Scheduler started.")

    def stop(self) -> None:
        self._stop.set()
        self.log("Scheduler stopping...")

    def _loop(self) -> None:
        while not self._stop.is_set():
            now = datetime.now()
            minute_key = now.strftime("%Y-%m-%d %H:%M")
            self._cleanup_last_fired(minute_key)
            with self._lock:
                events = list(self._events)
            for event in events:
                if not event.enabled:
                    continue
                if event.time_hhmm != now.strftime("%H:%M"):
                    continue
                if event.recurrence == "once":
                    if event.date_ymd != now.strftime("%Y-%m-%d"):
                        continue
                else:
                    if now.weekday() not in event.weekdays:
                        continue
                fire_key = f"{event.id}@{minute_key}"
                if fire_key in self._last_fired:
                    continue
                self._last_fired.add(fire_key)
                self.log(f"Triggering scheduled event '{event.label}' ({event.action}).")
                self.action_runner(event)
            time.sleep(1)

    def _cleanup_last_fired(self, current_minute_key: str) -> None:
        prefix = f"@{current_minute_key}"
        self._last_fired = {k for k in self._last_fired if k.endswith(prefix)}
