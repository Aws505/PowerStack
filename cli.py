#!/usr/bin/env python3
"""PowerStack CLI — command-line interface for the PowerStack Pi Controller.

Usage
-----
  python app.py list                      List all scheduled events
  python app.py next                      Show next upcoming events
  python app.py trigger <event>           Manually trigger an event action
  python app.py add --time HH:MM ...     Add a scheduled event
  python app.py remove <event>            Remove an event
  python app.py enable  <event>           Enable an event
  python app.py disable <event>           Pause an event
  python app.py suspend                   Suspend remote PC now
  python app.py wake                      Wake remote PC now
  python app.py toggle                    Toggle remote PC power now

  <event> can be a 1-based list index, an event ID (UUID), or a label.
"""
from __future__ import annotations

import argparse
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from config import AppConfig, ScheduleEvent
from control import RelayController, RemotePcController
from cron import CronManager


WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
LOG_PATH = Path.home() / ".powerstack" / "powerstack.log"


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------

def _log_to_file(message: str) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a") as fh:
            fh.write(f"[{stamp}] {message}\n")
    except Exception:
        pass


def _print_and_log(message: str) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{stamp}] {message}")
    _log_to_file(message)


# ---------------------------------------------------------------------------
# CLI core
# ---------------------------------------------------------------------------

class PowerStackCLI:
    def __init__(self, log: Callable[[str], None] = _print_and_log) -> None:
        self.log = log
        self.config = AppConfig.load()
        self.cron = CronManager()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _reload(self) -> None:
        self.config = AppConfig.load()

    def _save(self) -> None:
        self.config.save()
        try:
            self.cron.sync(self.config.schedule)
        except Exception as exc:
            self.log(f"[WARN] Crontab sync failed: {exc}")

    def _find_event(self, id_or_index: str) -> ScheduleEvent | None:
        # Try UUID match first
        for e in self.config.schedule:
            if e.id == id_or_index:
                return e
        # Try 1-based index
        try:
            idx = int(id_or_index) - 1
            if 0 <= idx < len(self.config.schedule):
                return self.config.schedule[idx]
        except ValueError:
            pass
        # Try case-insensitive label
        needle = id_or_index.lower()
        for e in self.config.schedule:
            if e.label.lower() == needle:
                return e
        return None

    def _make_relay(self) -> RelayController:
        return RelayController(self.config.relay, self.log)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def run_action(self, action: str) -> None:
        relay = self._make_relay()
        remote = RemotePcController(relay, self.log)
        if action == "suspend":
            result = remote.suspend(self.config.remote)
        elif action == "wake":
            if self.config.relay.wake_mode == "toggle":
                result = remote.toggle_power(self.config.relay.toggle_pulse_seconds)
            else:
                result = remote.wake_via_power_button(self.config.relay.wake_pulse_seconds)
        elif action == "toggle":
            result = remote.toggle_power(self.config.relay.toggle_pulse_seconds)
        else:
            self.log(f"[ERROR] Unknown action: {action}")
            return
        level = "OK" if result.ok else "ERROR"
        self.log(f"[{level}] {result.message}")

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    def cmd_list(self) -> None:
        events = self.config.schedule
        if not events:
            print("No scheduled events.")
            return
        col = "{:<4} {:<28} {:<9} {:<7} {:<22} {:<22} {}"
        print(col.format("#", "Label", "Action", "Time", "When", "Next Run", "Status"))
        print("-" * 108)
        for i, e in enumerate(events, 1):
            print(col.format(
                i,
                e.label[:27],
                e.action,
                e.time_hhmm,
                self._when_text(e)[:21],
                self._next_run_text(e)[:21],
                self._status_text(e),
            ))

    def cmd_next(self) -> None:
        upcoming: list[tuple[datetime, ScheduleEvent]] = []
        for e in self.config.schedule:
            dt = self._next_run_dt(e)
            if dt is not None:
                upcoming.append((dt, e))
        upcoming.sort(key=lambda x: x[0])
        if not upcoming:
            print("No upcoming events.")
            return
        col = "{:<4} {:<22} {:<28} {}"
        print(col.format("#", "Next Run", "Label", "Action"))
        print("-" * 70)
        for i, (dt, e) in enumerate(upcoming[:10], 1):
            print(col.format(i, dt.strftime("%a %Y-%m-%d %H:%M"), e.label[:27], e.action))

    def cmd_trigger(self, id_or_index: str) -> None:
        event = self._find_event(id_or_index)
        if event is None:
            print(f"Event not found: {id_or_index}", file=sys.stderr)
            sys.exit(1)
        self.log(f"Manually triggering '{event.label}' ({event.action}).")
        self.run_action(event.action)

    def cmd_internal_run(self, event_id: str) -> None:
        """Called by cron. Runs the event and auto-disables once-only events."""
        self._reload()
        event = self._find_event(event_id)
        if event is None:
            _log_to_file(f"[ERROR] cron _run: event not found: {event_id}")
            sys.exit(1)
        _log_to_file(f"Cron triggered '{event.label}' ({event.action}).")
        self.run_action(event.action)
        if event.recurrence == "once" and event.enabled:
            event.enabled = False
            self._save()
            _log_to_file(f"Auto-disabled one-time event '{event.label}'.")

    def cmd_enable(self, id_or_index: str) -> None:
        event = self._find_event(id_or_index)
        if event is None:
            print(f"Event not found: {id_or_index}", file=sys.stderr)
            sys.exit(1)
        event.enabled = True
        self._save()
        print(f"Enabled: {event.label}")

    def cmd_disable(self, id_or_index: str) -> None:
        event = self._find_event(id_or_index)
        if event is None:
            print(f"Event not found: {id_or_index}", file=sys.stderr)
            sys.exit(1)
        event.enabled = False
        self._save()
        print(f"Disabled: {event.label}")

    def cmd_remove(self, id_or_index: str) -> None:
        event = self._find_event(id_or_index)
        if event is None:
            print(f"Event not found: {id_or_index}", file=sys.stderr)
            sys.exit(1)
        label = event.label
        self.config.schedule = [e for e in self.config.schedule if e.id != event.id]
        self._save()
        print(f"Removed: {label}")

    def cmd_add(
        self,
        label: str | None,
        action: str,
        time_hhmm: str,
        recurrence: str,
        weekdays: list[int],
        date_ymd: str,
        enabled: bool,
    ) -> None:
        if not _valid_hhmm(time_hhmm):
            print(f"Invalid time '{time_hhmm}' — expected HH:MM (24-hour).", file=sys.stderr)
            sys.exit(1)
        if recurrence == "once" and not _valid_ymd(date_ymd):
            print(f"Invalid date '{date_ymd}' — expected YYYY-MM-DD.", file=sys.stderr)
            sys.exit(1)
        if recurrence == "weekly" and not weekdays:
            print("Weekly recurrence requires at least one weekday (--days).", file=sys.stderr)
            sys.exit(1)
        event = ScheduleEvent(
            id=str(uuid.uuid4()),
            label=label or f"{action} {time_hhmm}",
            action=action,
            time_hhmm=time_hhmm,
            recurrence=recurrence,
            date_ymd=date_ymd,
            weekdays=weekdays,
            enabled=enabled,
        )
        self.config.schedule.append(event)
        self._save()
        print(f"Added: {event.label}  (ID: {event.id})")

    # ------------------------------------------------------------------
    # Display helpers
    # ------------------------------------------------------------------

    def _status_text(self, e: ScheduleEvent) -> str:
        if e.enabled:
            return "Enabled"
        if e.recurrence == "once" and e.date_ymd:
            try:
                dt = datetime.strptime(f"{e.date_ymd} {e.time_hhmm}", "%Y-%m-%d %H:%M")
                if datetime.now() >= dt:
                    return "Completed"
            except ValueError:
                pass
        return "Paused"

    def _when_text(self, e: ScheduleEvent) -> str:
        if e.recurrence == "once":
            return f"Once {e.date_ymd}"
        return ",".join(WEEKDAY_LABELS[d] for d in e.weekdays)

    def _next_run_text(self, e: ScheduleEvent) -> str:
        dt = self._next_run_dt(e)
        return dt.strftime("%a %Y-%m-%d %H:%M") if dt else "-"

    def _next_run_dt(self, e: ScheduleEvent) -> datetime | None:
        if not e.enabled:
            return None
        now = datetime.now()
        if e.recurrence == "once":
            try:
                target = datetime.strptime(f"{e.date_ymd} {e.time_hhmm}", "%Y-%m-%d %H:%M")
                return None if target < now else target
            except ValueError:
                return None
        if not e.weekdays or ":" not in e.time_hhmm:
            return None
        hh, mm = (int(x) for x in e.time_hhmm.split(":"))
        for offset in range(8):
            candidate = (now + timedelta(days=offset)).replace(
                hour=hh, minute=mm, second=0, microsecond=0
            )
            if candidate.weekday() in e.weekdays and candidate >= now:
                return candidate
        return None


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _valid_hhmm(value: str) -> bool:
    parts = value.split(":")
    if len(parts) != 2:
        return False
    try:
        hh, mm = int(parts[0]), int(parts[1])
    except ValueError:
        return False
    return 0 <= hh <= 23 and 0 <= mm <= 59


def _valid_ymd(value: str) -> bool:
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _parse_days(days_str: str) -> list[int]:
    """Parse 'mon,tue,fri' or '0,1,4' into a sorted list of ints (0=Mon)."""
    day_map = {
        "mon": 0, "monday": 0,
        "tue": 1, "tuesday": 1,
        "wed": 2, "wednesday": 2,
        "thu": 3, "thursday": 3,
        "fri": 4, "friday": 4,
        "sat": 5, "saturday": 5,
        "sun": 6, "sunday": 6,
    }
    result: list[int] = []
    for part in days_str.split(","):
        p = part.strip().lower()
        if p in day_map:
            result.append(day_map[p])
        else:
            try:
                d = int(p)
                if 0 <= d <= 6:
                    result.append(d)
                else:
                    print(f"Day index out of range (0-6): {p}", file=sys.stderr)
            except ValueError:
                print(f"Unknown day: {p}", file=sys.stderr)
    return sorted(set(result))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="powerstack",
        description="PowerStack Pi Controller — CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  python app.py list\n"
            "  python app.py next\n"
            "  python app.py add --time 22:30 --action suspend --days mon,tue,wed,thu,fri\n"
            "  python app.py add --time 08:00 --action wake --recurrence once --date 2026-03-20\n"
            "  python app.py trigger 1\n"
            "  python app.py enable 'Nightly suspend'\n"
            "  python app.py disable 2\n"
            "  python app.py remove 3\n"
            "  python app.py suspend\n"
            "  python app.py wake\n"
        ),
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    sub.add_parser("list", help="List all scheduled events")
    sub.add_parser("next", help="Show next upcoming events (up to 10)")

    p = sub.add_parser("trigger", help="Manually trigger a scheduled event")
    p.add_argument("event", help="Index, ID, or label")

    p = sub.add_parser("enable", help="Enable a scheduled event")
    p.add_argument("event", help="Index, ID, or label")

    p = sub.add_parser("disable", help="Disable/pause a scheduled event")
    p.add_argument("event", help="Index, ID, or label")

    p = sub.add_parser("remove", help="Remove a scheduled event")
    p.add_argument("event", help="Index, ID, or label")

    p = sub.add_parser("add", help="Add a new scheduled event")
    p.add_argument("--label", "-l", default=None, help="Human-readable label")
    p.add_argument(
        "--action", "-a",
        choices=["suspend", "wake", "toggle"],
        default="suspend",
        help="Action to perform (default: suspend)",
    )
    p.add_argument("--time", "-t", required=True, metavar="HH:MM", help="Time in 24-hour HH:MM format")
    p.add_argument(
        "--recurrence", "-r",
        choices=["weekly", "once"],
        default="weekly",
        help="Recurrence (default: weekly)",
    )
    p.add_argument(
        "--days", "-d",
        default=None,
        metavar="DAYS",
        help="Weekdays for weekly events: comma-separated names or 0-6 (0=Mon). Default: all",
    )
    p.add_argument(
        "--date",
        default=None,
        metavar="YYYY-MM-DD",
        help="Date for once events",
    )
    p.add_argument("--disabled", action="store_true", help="Create the event in disabled state")

    sub.add_parser("suspend", help="Suspend the remote PC immediately")
    sub.add_parser("wake", help="Wake the remote PC immediately")
    sub.add_parser("toggle", help="Toggle the remote PC power immediately")

    # Internal command invoked by cron — suppressed from help
    p = sub.add_parser("_run", help=argparse.SUPPRESS)
    p.add_argument("event_id")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    cli = PowerStackCLI()

    if args.command == "list":
        cli.cmd_list()
    elif args.command == "next":
        cli.cmd_next()
    elif args.command == "trigger":
        cli.cmd_trigger(args.event)
    elif args.command == "enable":
        cli.cmd_enable(args.event)
    elif args.command == "disable":
        cli.cmd_disable(args.event)
    elif args.command == "remove":
        cli.cmd_remove(args.event)
    elif args.command == "add":
        weekdays = _parse_days(args.days) if args.days else list(range(7))
        cli.cmd_add(
            label=args.label,
            action=args.action,
            time_hhmm=args.time,
            recurrence=args.recurrence,
            weekdays=weekdays,
            date_ymd=args.date or "",
            enabled=not args.disabled,
        )
    elif args.command == "suspend":
        cli.run_action("suspend")
    elif args.command == "wake":
        cli.run_action("wake")
    elif args.command == "toggle":
        cli.run_action("toggle")
    elif args.command == "_run":
        cli.cmd_internal_run(args.event_id)


if __name__ == "__main__":
    main()
