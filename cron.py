from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

from config import ScheduleEvent


MARKER_BEGIN = "# BEGIN POWERSTACK"
MARKER_END = "# END POWERSTACK"

_CLI_PATH = Path(__file__).resolve().parent / "cli.py"


class CronManager:
    """Manages the PowerStack block inside the user's crontab."""

    def sync(self, events: list[ScheduleEvent]) -> None:
        """Rebuild the PowerStack crontab block from the current event list."""
        lines = self._read_crontab()
        stripped = self._strip_block(lines)
        block = self._build_block(events)
        self._write_crontab(stripped + block)

    def remove_all(self) -> None:
        """Remove the entire PowerStack crontab block."""
        lines = self._read_crontab()
        stripped = self._strip_block(lines)
        self._write_crontab(stripped)

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _cron_expr(self, event: ScheduleEvent) -> str:
        hh, mm = event.time_hhmm.split(":")
        if event.recurrence == "once":
            dt = datetime.strptime(event.date_ymd, "%Y-%m-%d")
            return f"{mm} {hh} {dt.day} {dt.month} *"
        # Python weekday 0=Mon → cron weekday 1=Mon; Sun is 0 in cron
        days = ",".join(str((d + 1) % 7) for d in sorted(event.weekdays))
        return f"{mm} {hh} * * {days}"

    def _build_block(self, events: list[ScheduleEvent]) -> list[str]:
        py = sys.executable
        cli = str(_CLI_PATH)
        lines: list[str] = [MARKER_BEGIN]
        for event in events:
            if not event.enabled:
                continue
            try:
                expr = self._cron_expr(event)
            except Exception:
                continue
            lines.append(f"{expr} {py} {cli} _run {event.id}  # {event.label}")
        lines.append(MARKER_END)
        return lines

    def _read_crontab(self) -> list[str]:
        result = subprocess.run(
            ["crontab", "-l"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return []
        return result.stdout.splitlines()

    def _strip_block(self, lines: list[str]) -> list[str]:
        out: list[str] = []
        inside = False
        for line in lines:
            if line.strip() == MARKER_BEGIN:
                inside = True
            elif line.strip() == MARKER_END:
                inside = False
            elif not inside:
                out.append(line)
        return out

    def _write_crontab(self, lines: list[str]) -> None:
        content = "\n".join(lines)
        if content and not content.endswith("\n"):
            content += "\n"
        proc = subprocess.run(
            ["crontab", "-"],
            input=content,
            text=True,
            capture_output=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"Failed to write crontab: {proc.stderr.strip()}")
