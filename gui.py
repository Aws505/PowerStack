from __future__ import annotations

import queue
import uuid
from datetime import datetime, timedelta
import tkinter as tk
from tkinter import messagebox, ttk

from config import AppConfig, RelayConfig, ScheduleEvent
from control import RelayController, RemotePcController, run_async
from scheduler import EventScheduler


WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
KS0212_CHANNEL_TO_BCM = {
    "Relay 1 (BCM 4)": 4,
    "Relay 2 (BCM 22)": 22,
    "Relay 3 (BCM 6)": 6,
    "Relay 4 (BCM 26)": 26,
}
KS0212_CUSTOM = "Custom (manual pin)"


class PowerStackApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("PowerStack Pi Controller")
        self.root.geometry("1040x720")

        self.config = AppConfig.load()
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.log_history: list[str] = []

        self.relay = RelayController(self.config.relay, self._log)
        self.remote = RemotePcController(self.relay, self._log)
        self.scheduler = EventScheduler(self._log, self._run_scheduled_event)
        self.scheduler.set_events(self.config.schedule)

        self.selected_event_id: str | None = None

        self.suspend_config_window: tk.Toplevel | None = None
        self.schedule_config_window: tk.Toplevel | None = None
        self.logs_window: tk.Toplevel | None = None

        self.logs_text: tk.Text | None = None
        self.main_status_var = tk.StringVar(value="Ready")
        self.selected_label_var = tk.StringVar(value="None selected")
        self.selected_status_var = tk.StringVar(value="-")
        self.selected_next_var = tk.StringVar(value="-")

        self.main_schedule_table: ttk.Treeview | None = None

        self._build_vars()
        self._build_main_ui()
        self._refresh_schedule_tables()

        self.scheduler.start()
        self._drain_log_queue()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_vars(self) -> None:
        r = self.config.remote
        relay = self.config.relay
        self.host_var = tk.StringVar(value=r.host)
        self.user_var = tk.StringVar(value=r.user)
        self.port_var = tk.StringVar(value=str(r.port))
        self.key_var = tk.StringVar(value=r.ssh_key_path)
        self.suspend_cmd_var = tk.StringVar(value=r.suspend_command)

        self.gpio_pin_var = tk.StringVar(value=str(relay.gpio_pin))
        self.relay_channel_var = tk.StringVar(value=self._channel_label_for_pin(relay.gpio_pin))
        self.active_high_var = tk.BooleanVar(value=relay.active_high)
        self.pulse_var = tk.StringVar(value=str(relay.pulse_seconds))
        self.holdoff_var = tk.StringVar(value=str(relay.holdoff_seconds))

        self.event_label_var = tk.StringVar(value="")
        self.event_action_var = tk.StringVar(value="suspend")
        self.event_recurrence_var = tk.StringVar(value="weekly")
        self.event_date_var = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d"))
        self.event_time_var = tk.StringVar(value=datetime.now().strftime("%H:%M"))
        self.event_enabled_var = tk.BooleanVar(value=True)
        self.weekday_vars = [tk.BooleanVar(value=True) for _ in range(7)]

        self.event_date_entry: ttk.Entry | None = None
        self.days_frame: ttk.Frame | None = None

    def _build_main_ui(self) -> None:
        main = ttk.Frame(self.root, padding=12)
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=1)

        header = ttk.Frame(main)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="PowerStack Dashboard", font=("TkDefaultFont", 12, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        nav = ttk.Frame(header)
        nav.grid(row=0, column=1, sticky="e")
        ttk.Button(nav, text="Suspend Config", command=self._open_suspend_config_window).pack(side="left", padx=4)
        ttk.Button(nav, text="Schedule Config", command=self._open_schedule_config_window).pack(side="left", padx=4)
        ttk.Button(nav, text="Logs", command=self._open_logs_window).pack(side="left", padx=4)

        content = ttk.Frame(main)
        content.grid(row=1, column=0, sticky="nsew")
        content.columnconfigure(0, weight=0)
        content.columnconfigure(1, weight=1)
        content.rowconfigure(0, weight=1)

        left_rail = ttk.Frame(content)
        left_rail.grid(row=0, column=0, sticky="nsw", padx=(0, 10))

        system_card = ttk.LabelFrame(left_rail, text="System")
        system_card.pack(fill="x", pady=(0, 8))
        ttk.Button(system_card, text="Suspend Now", command=lambda: self._run_action("suspend")).pack(
            fill="x", padx=8, pady=(8, 4)
        )
        ttk.Button(system_card, text="Wake Now", command=lambda: self._run_action("wake")).pack(
            fill="x", padx=8, pady=(0, 8)
        )

        selected_card = ttk.LabelFrame(left_rail, text="Selected Event")
        selected_card.pack(fill="x", pady=(0, 8))
        ttk.Label(selected_card, textvariable=self.selected_label_var).pack(anchor="w", padx=8, pady=(8, 2))
        ttk.Label(selected_card, textvariable=self.selected_status_var).pack(anchor="w", padx=8, pady=2)
        ttk.Label(selected_card, textvariable=self.selected_next_var).pack(anchor="w", padx=8, pady=(2, 8))
        ttk.Button(selected_card, text="Start", command=lambda: self._set_selected_event_enabled(True)).pack(
            fill="x", padx=8, pady=(0, 4)
        )
        ttk.Button(selected_card, text="Pause", command=lambda: self._set_selected_event_enabled(False)).pack(
            fill="x", padx=8, pady=(0, 4)
        )
        ttk.Button(selected_card, text="Run Now", command=self._run_selected_event_now).pack(
            fill="x", padx=8, pady=(0, 8)
        )
        ttk.Separator(selected_card, orient="horizontal").pack(fill="x", padx=8, pady=(0, 6))
        ttk.Button(selected_card, text="Add Event", command=self._open_schedule_config_window).pack(
            fill="x", padx=8, pady=(0, 4)
        )
        ttk.Button(selected_card, text="Remove Event", command=self._delete_selected_event).pack(
            fill="x", padx=8, pady=(0, 8)
        )

        legend_card = ttk.LabelFrame(left_rail, text="Legend")
        legend_card.pack(fill="x")
        ttk.Label(legend_card, text="Enabled = green").pack(anchor="w", padx=8, pady=(8, 2))
        ttk.Label(legend_card, text="Paused = amber").pack(anchor="w", padx=8, pady=2)
        ttk.Label(legend_card, text="Completed = gray").pack(anchor="w", padx=8, pady=(2, 8))

        schedule_panel = ttk.LabelFrame(content, text="Schedule Overview")
        schedule_panel.grid(row=0, column=1, sticky="nsew")
        schedule_panel.rowconfigure(0, weight=1)
        schedule_panel.columnconfigure(0, weight=1)

        self.main_schedule_table = self._create_schedule_table(schedule_panel)
        self.main_schedule_table.grid(row=0, column=0, sticky="nsew")
        self.main_schedule_table.bind("<<TreeviewSelect>>", self._on_main_schedule_selected)

        scroll = ttk.Scrollbar(schedule_panel, orient="vertical", command=self.main_schedule_table.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.main_schedule_table.configure(yscrollcommand=scroll.set)

        status_bar = ttk.Frame(main)
        status_bar.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        ttk.Label(status_bar, textvariable=self.main_status_var).pack(side="left")

    def _create_schedule_table(self, parent: tk.Widget) -> ttk.Treeview:
        table = ttk.Treeview(
            parent,
            columns=("label", "action", "time", "when", "next", "status"),
            show="headings",
            selectmode="browse",
        )
        specs = [
            ("label", "Label", 220),
            ("action", "Action", 80),
            ("time", "Time", 70),
            ("when", "When", 190),
            ("next", "Next Run", 160),
            ("status", "Status", 90),
        ]
        for col, text, width in specs:
            table.heading(col, text=text)
            table.column(col, width=width, anchor="w")
        table.tag_configure("enabled", foreground="#1f7a2e")
        table.tag_configure("disabled", foreground="#b06c00")
        table.tag_configure("completed", foreground="#5f6b76")
        return table

    def _open_suspend_config_window(self) -> None:
        if self.suspend_config_window and self.suspend_config_window.winfo_exists():
            self.suspend_config_window.lift()
            self.suspend_config_window.focus_force()
            return

        win = tk.Toplevel(self.root)
        self.suspend_config_window = win
        win.title("Suspend Config")
        win.geometry("760x320")
        win.protocol("WM_DELETE_WINDOW", self._close_suspend_config_window)

        frame = ttk.Frame(win, padding=12)
        frame.pack(fill="both", expand=True)
        for i in range(4):
            frame.columnconfigure(i, weight=1)

        items = [
            ("Host", self.host_var),
            ("User", self.user_var),
            ("Port", self.port_var),
            ("SSH Key", self.key_var),
            ("Suspend Cmd", self.suspend_cmd_var),
            ("Pulse (s)", self.pulse_var),
            ("Holdoff (s)", self.holdoff_var),
        ]

        for idx, (label, var) in enumerate(items):
            row = idx // 2
            col = (idx % 2) * 2
            ttk.Label(frame, text=label).grid(row=row, column=col, sticky="w", padx=4, pady=4)
            ttk.Entry(frame, textvariable=var).grid(row=row, column=col + 1, sticky="ew", padx=4, pady=4)

        row_base = 4
        ttk.Label(frame, text="Relay Channel").grid(row=row_base, column=0, sticky="w", padx=4, pady=4)
        channel_combo = ttk.Combobox(
            frame,
            textvariable=self.relay_channel_var,
            values=[*KS0212_CHANNEL_TO_BCM.keys(), KS0212_CUSTOM],
            state="readonly",
        )
        channel_combo.grid(row=row_base, column=1, sticky="ew", padx=4, pady=4)
        channel_combo.bind("<<ComboboxSelected>>", self._on_channel_selected)

        ttk.Label(frame, text="GPIO Pin").grid(row=row_base, column=2, sticky="w", padx=4, pady=4)
        ttk.Entry(frame, textvariable=self.gpio_pin_var).grid(row=row_base, column=3, sticky="ew", padx=4, pady=4)

        ttk.Checkbutton(frame, text="Relay Active High", variable=self.active_high_var).grid(
            row=row_base + 1, column=0, columnspan=2, sticky="w", padx=4, pady=4
        )

        button_row = ttk.Frame(frame)
        button_row.grid(row=row_base + 2, column=0, columnspan=4, sticky="e", pady=(8, 0))
        ttk.Button(button_row, text="Test Relay", command=self._test_relay_from_form).pack(side="left", padx=6)
        ttk.Button(button_row, text="Save", command=self._save_settings).pack(side="left", padx=6)

    def _open_schedule_config_window(self) -> None:
        if self.schedule_config_window and self.schedule_config_window.winfo_exists():
            self.schedule_config_window.lift()
            self.schedule_config_window.focus_force()
            return

        win = tk.Toplevel(self.root)
        self.schedule_config_window = win
        win.title("Add Schedule Event")
        win.geometry("420x430")
        win.protocol("WM_DELETE_WINDOW", self._close_schedule_config_window)

        frame = ttk.Frame(win, padding=12)
        frame.pack(fill="both", expand=True)
        form = ttk.LabelFrame(frame, text="New Event")
        form.pack(fill="both", expand=True)
        for i in range(2):
            form.columnconfigure(i, weight=1)

        ttk.Label(form, text="Label").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        ttk.Entry(form, textvariable=self.event_label_var).grid(row=0, column=1, sticky="ew", padx=4, pady=4)

        ttk.Label(form, text="Action").grid(row=1, column=0, sticky="w", padx=4, pady=4)
        ttk.Combobox(
            form,
            textvariable=self.event_action_var,
            values=["suspend", "wake"],
            state="readonly",
        ).grid(row=1, column=1, sticky="ew", padx=4, pady=4)

        ttk.Label(form, text="Recurrence").grid(row=2, column=0, sticky="w", padx=4, pady=4)
        recurrence_combo = ttk.Combobox(
            form,
            textvariable=self.event_recurrence_var,
            values=["weekly", "once"],
            state="readonly",
        )
        recurrence_combo.grid(row=2, column=1, sticky="ew", padx=4, pady=4)
        recurrence_combo.bind("<<ComboboxSelected>>", self._on_event_recurrence_changed)

        ttk.Label(form, text="Date (YYYY-MM-DD)").grid(row=3, column=0, sticky="w", padx=4, pady=4)
        self.event_date_entry = ttk.Entry(form, textvariable=self.event_date_var)
        self.event_date_entry.grid(row=3, column=1, sticky="ew", padx=4, pady=4)

        ttk.Label(form, text="Time (HH:MM)").grid(row=4, column=0, sticky="w", padx=4, pady=4)
        ttk.Entry(form, textvariable=self.event_time_var).grid(row=4, column=1, sticky="ew", padx=4, pady=4)

        ttk.Checkbutton(form, text="Enabled", variable=self.event_enabled_var).grid(
            row=5, column=0, columnspan=2, sticky="w", padx=4, pady=4
        )

        ttk.Label(form, text="Weekdays").grid(row=6, column=0, sticky="nw", padx=4, pady=4)
        self.days_frame = ttk.Frame(form)
        self.days_frame.grid(row=6, column=1, sticky="w", padx=4, pady=4)
        for i, label in enumerate(WEEKDAY_LABELS):
            ttk.Checkbutton(self.days_frame, text=label, variable=self.weekday_vars[i]).grid(
                row=i // 3, column=i % 3, sticky="w", padx=2, pady=2
            )

        form_buttons = ttk.Frame(form)
        form_buttons.grid(row=7, column=0, columnspan=2, sticky="ew", padx=4, pady=8)
        ttk.Button(form_buttons, text="New/Clear", command=self._reset_event_form).pack(side="left")
        ttk.Button(form_buttons, text="Add Event", command=self._add_event).pack(side="right")

        self._update_event_form_mode()
        self._reset_event_form()

    def _open_logs_window(self) -> None:
        if self.logs_window and self.logs_window.winfo_exists():
            self.logs_window.lift()
            self.logs_window.focus_force()
            return

        win = tk.Toplevel(self.root)
        self.logs_window = win
        win.title("Logs")
        win.geometry("900x420")
        win.protocol("WM_DELETE_WINDOW", self._close_logs_window)

        frame = ttk.Frame(win, padding=12)
        frame.pack(fill="both", expand=True)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        self.logs_text = tk.Text(frame, wrap="word")
        self.logs_text.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.logs_text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.logs_text.configure(yscrollcommand=scroll.set)

        for line in self.log_history:
            self.logs_text.insert("end", line + "\n")
        self.logs_text.see("end")

    def _close_suspend_config_window(self) -> None:
        if self.suspend_config_window and self.suspend_config_window.winfo_exists():
            self.suspend_config_window.destroy()
        self.suspend_config_window = None

    def _close_schedule_config_window(self) -> None:
        if self.schedule_config_window and self.schedule_config_window.winfo_exists():
            self.schedule_config_window.destroy()
        self.schedule_config_window = None
        self.event_date_entry = None
        self.days_frame = None

    def _close_logs_window(self) -> None:
        if self.logs_window and self.logs_window.winfo_exists():
            self.logs_window.destroy()
        self.logs_window = None
        self.logs_text = None

    def _save_settings(self) -> None:
        try:
            self.config.remote.host = self.host_var.get().strip()
            self.config.remote.user = self.user_var.get().strip()
            self.config.remote.port = int(self.port_var.get().strip())
            self.config.remote.ssh_key_path = self.key_var.get().strip()
            self.config.remote.suspend_command = self.suspend_cmd_var.get().strip() or "systemctl suspend"
            self.config.relay = self._relay_config_from_form()
            self.relay.reconfigure(self.config.relay)
            self.config.save()
            self._log("Settings saved.")
        except ValueError as exc:
            messagebox.showerror("Invalid settings", str(exc))

    def _channel_label_for_pin(self, pin: int) -> str:
        for label, bcm in KS0212_CHANNEL_TO_BCM.items():
            if bcm == pin:
                return label
        return KS0212_CUSTOM

    def _on_channel_selected(self, _event: object | None = None) -> None:
        self._apply_channel_selection_to_gpio_pin()

    def _apply_channel_selection_to_gpio_pin(self) -> None:
        label = self.relay_channel_var.get()
        if label in KS0212_CHANNEL_TO_BCM:
            self.gpio_pin_var.set(str(KS0212_CHANNEL_TO_BCM[label]))

    def _relay_config_from_form(self) -> RelayConfig:
        self._apply_channel_selection_to_gpio_pin()
        return RelayConfig(
            gpio_pin=int(self.gpio_pin_var.get().strip()),
            active_high=bool(self.active_high_var.get()),
            pulse_seconds=float(self.pulse_var.get().strip()),
            holdoff_seconds=float(self.holdoff_var.get().strip()),
        )

    def _test_relay_from_form(self) -> None:
        try:
            temp_config = self._relay_config_from_form()
            self.relay.reconfigure(temp_config)
            run_async(self.remote.wake_via_power_button, self._log)
            self._log("Testing relay with current form settings (not saved).")
        except ValueError as exc:
            messagebox.showerror("Invalid relay settings", str(exc))

    def _run_action(self, action: str) -> None:
        if action == "suspend":
            run_async(lambda: self.remote.suspend(self.config.remote), self._log)
        elif action == "wake":
            run_async(self.remote.wake_via_power_button, self._log)
        else:
            self._log(f"[ERROR] Unknown action: {action}")

    def _run_scheduled_event(self, event: ScheduleEvent) -> None:
        self._run_action(event.action)
        if event.recurrence == "once":
            self.root.after(0, lambda event_id=event.id: self._auto_disable_one_time_event(event_id))

    def _add_event(self) -> None:
        event = self._event_from_form()
        if event is None:
            return
        event.id = str(uuid.uuid4())
        self.config.schedule.append(event)
        self._persist_schedule_changes()
        self._refresh_schedule_tables()
        self._reset_event_form()
        self._log(f"Added schedule event '{event.label}'.")

    def _delete_selected_event(self) -> None:
        event_id = self.selected_event_id
        if not event_id:
            messagebox.showerror("No selection", "Select an event in the main schedule table.")
            return
        before = len(self.config.schedule)
        self.config.schedule = [e for e in self.config.schedule if e.id != event_id]
        if len(self.config.schedule) == before:
            return
        self.selected_event_id = None
        self._persist_schedule_changes()
        self._refresh_schedule_tables()
        self._reset_event_form()
        self._log("Deleted selected schedule event.")

    def _set_selected_event_enabled(self, enabled: bool) -> None:
        event_id = self.selected_event_id
        if not event_id:
            return
        for event in self.config.schedule:
            if event.id == event_id:
                event.enabled = enabled
                self._persist_schedule_changes()
                self._refresh_schedule_tables()
                self._set_selected_event(event_id)
                if self.selected_event_id == event_id:
                    self.event_enabled_var.set(enabled)
                verb = "Started" if enabled else "Paused"
                self._log(f"{verb} event '{event.label}'.")
                return

    def _run_selected_event_now(self) -> None:
        event_id = self.selected_event_id
        if not event_id:
            return
        for event in self.config.schedule:
            if event.id == event_id:
                self._log(f"Running selected event now: '{event.label}' ({event.action}).")
                self._run_action(event.action)
                return

    def _on_main_schedule_selected(self, _event: object | None = None) -> None:
        if not self.main_schedule_table:
            return
        selected = self.main_schedule_table.selection()
        if not selected:
            return
        event_id = selected[0]
        self._set_selected_event(event_id)

    def _set_selected_event(self, event_id: str) -> None:
        self.selected_event_id = event_id
        self._load_selected_event_into_form(event_id)
        if self.main_schedule_table and self.main_schedule_table.exists(event_id):
            self.main_schedule_table.selection_set(event_id)
        self._update_selected_summary(event_id)

    def _load_selected_event_into_form(self, event_id: str) -> None:
        for event in self.config.schedule:
            if event.id != event_id:
                continue
            self.event_label_var.set(event.label)
            self.event_action_var.set(event.action)
            self.event_recurrence_var.set(event.recurrence or "weekly")
            self.event_date_var.set(event.date_ymd or datetime.now().strftime("%Y-%m-%d"))
            self.event_time_var.set(event.time_hhmm)
            self.event_enabled_var.set(event.enabled)
            for i, var in enumerate(self.weekday_vars):
                var.set(i in event.weekdays)
            self._update_event_form_mode()
            return

    def _event_from_form(self) -> ScheduleEvent | None:
        recurrence = self.event_recurrence_var.get().strip()
        time_text = self.event_time_var.get().strip()
        if not self._valid_hhmm(time_text):
            messagebox.showerror("Invalid time", "Time must be HH:MM (24-hour).")
            return None
        if recurrence not in {"weekly", "once"}:
            messagebox.showerror("Invalid recurrence", "Recurrence must be 'weekly' or 'once'.")
            return None

        date_ymd = self.event_date_var.get().strip()
        weekdays: list[int]
        if recurrence == "once":
            if not self._valid_ymd(date_ymd):
                messagebox.showerror("Invalid date", "Date must be YYYY-MM-DD.")
                return None
            weekdays = []
        else:
            weekdays = [i for i, var in enumerate(self.weekday_vars) if var.get()]
            if not weekdays:
                messagebox.showerror("Invalid days", "Select at least one weekday.")
                return None
            date_ymd = ""

        return ScheduleEvent(
            id=str(uuid.uuid4()),
            label=self.event_label_var.get().strip() or f"{self.event_action_var.get()} {time_text}",
            action=self.event_action_var.get(),
            time_hhmm=time_text,
            recurrence=recurrence,
            date_ymd=date_ymd,
            weekdays=weekdays,
            enabled=bool(self.event_enabled_var.get()),
        )

    def _reset_event_form(self) -> None:
        self.selected_event_id = None
        self._clear_selected_summary()
        self.event_label_var.set("")
        self.event_action_var.set("suspend")
        self.event_recurrence_var.set("weekly")
        self.event_date_var.set(datetime.now().strftime("%Y-%m-%d"))
        self.event_time_var.set(datetime.now().strftime("%H:%M"))
        self.event_enabled_var.set(True)
        for var in self.weekday_vars:
            var.set(True)
        self._update_event_form_mode()

    def _on_event_recurrence_changed(self, _event: object | None = None) -> None:
        self._update_event_form_mode()

    def _update_event_form_mode(self) -> None:
        recurrence = self.event_recurrence_var.get().strip() or "weekly"
        if self.event_date_entry is not None:
            self.event_date_entry.configure(state="normal" if recurrence == "once" else "disabled")
        if self.days_frame is not None:
            for child in self.days_frame.winfo_children():
                child_state = "disabled" if recurrence == "once" else "normal"
                try:
                    child.configure(state=child_state)
                except tk.TclError:
                    pass

    def _persist_schedule_changes(self) -> None:
        self.config.save()
        self.scheduler.set_events(self.config.schedule)

    def _refresh_schedule_tables(self) -> None:
        self._populate_schedule_table(self.main_schedule_table)
        if self.selected_event_id:
            self._update_selected_summary(self.selected_event_id)
        else:
            self._clear_selected_summary()

    def _populate_schedule_table(self, table: ttk.Treeview | None) -> None:
        if table is None:
            return
        for item in table.get_children():
            table.delete(item)

        for event in self.config.schedule:
            when_text = self._event_when_text(event)
            next_text = self._event_next_run_text(event)
            status = self._event_status_text(event)
            tag = self._event_status_tag(status)
            table.insert(
                "",
                "end",
                iid=event.id,
                values=(event.label, event.action, event.time_hhmm, when_text, next_text, status),
                tags=(tag,),
            )

        if self.selected_event_id and table.exists(self.selected_event_id):
            table.selection_set(self.selected_event_id)

    def _update_selected_summary(self, event_id: str) -> None:
        for event in self.config.schedule:
            if event.id != event_id:
                continue
            self.selected_label_var.set(f"Event: {event.label}")
            self.selected_status_var.set(f"Status: {self._event_status_text(event)}")
            self.selected_next_var.set(f"Next: {self._event_next_run_text(event)}")
            return
        self._clear_selected_summary()

    def _clear_selected_summary(self) -> None:
        self.selected_label_var.set("None selected")
        self.selected_status_var.set("Status: -")
        self.selected_next_var.set("Next: -")

    def _event_when_text(self, event: ScheduleEvent) -> str:
        if event.recurrence == "once":
            return f"Once {event.date_ymd}"
        return ",".join(WEEKDAY_LABELS[d] for d in event.weekdays)

    def _event_next_run_text(self, event: ScheduleEvent) -> str:
        if not event.enabled:
            return "-"
        now = datetime.now()
        if event.recurrence == "once":
            try:
                target = datetime.strptime(f"{event.date_ymd} {event.time_hhmm}", "%Y-%m-%d %H:%M")
            except ValueError:
                return "Invalid date/time"
            return "Past due" if target < now else target.strftime("%Y-%m-%d %H:%M")

        next_run = self._next_weekly_run(now, event)
        return next_run.strftime("%a %Y-%m-%d %H:%M") if next_run else "-"

    def _next_weekly_run(self, now: datetime, event: ScheduleEvent) -> datetime | None:
        if not event.weekdays or not self._valid_hhmm(event.time_hhmm):
            return None
        hh, mm = [int(part) for part in event.time_hhmm.split(":")]
        for offset in range(0, 8):
            candidate_day = now + timedelta(days=offset)
            if candidate_day.weekday() not in event.weekdays:
                continue
            candidate = candidate_day.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if candidate >= now:
                return candidate
        return None

    def _event_status_text(self, event: ScheduleEvent) -> str:
        if event.enabled:
            return "Enabled"
        if event.recurrence == "once" and event.date_ymd and self._one_time_event_has_passed(event):
            return "Completed"
        return "Paused"

    def _event_status_tag(self, status: str) -> str:
        if status == "Enabled":
            return "enabled"
        if status == "Completed":
            return "completed"
        return "disabled"

    def _auto_disable_one_time_event(self, event_id: str) -> None:
        for event in self.config.schedule:
            if event.id == event_id and event.recurrence == "once" and event.enabled:
                event.enabled = False
                self._persist_schedule_changes()
                self._refresh_schedule_tables()
                if self.selected_event_id == event_id:
                    self.event_enabled_var.set(False)
                self._log(f"Auto-disabled one-time event '{event.label}' after firing.")
                return

    def _one_time_event_has_passed(self, event: ScheduleEvent) -> bool:
        try:
            scheduled = datetime.strptime(f"{event.date_ymd} {event.time_hhmm}", "%Y-%m-%d %H:%M")
        except ValueError:
            return False
        return datetime.now() >= scheduled

    def _valid_hhmm(self, value: str) -> bool:
        parts = value.split(":")
        if len(parts) != 2:
            return False
        try:
            hh = int(parts[0])
            mm = int(parts[1])
        except ValueError:
            return False
        return 0 <= hh <= 23 and 0 <= mm <= 59

    def _valid_ymd(self, value: str) -> bool:
        try:
            datetime.strptime(value, "%Y-%m-%d")
            return True
        except ValueError:
            return False

    def _log(self, message: str) -> None:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.log_queue.put(f"[{stamp}] {message}")

    def _drain_log_queue(self) -> None:
        try:
            while True:
                line = self.log_queue.get_nowait()
                self.log_history.append(line)
                self.main_status_var.set(line)
                if self.logs_text is not None and self.logs_window and self.logs_window.winfo_exists():
                    self.logs_text.insert("end", line + "\n")
                    self.logs_text.see("end")
        except queue.Empty:
            pass
        self.root.after(200, self._drain_log_queue)

    def _on_close(self) -> None:
        self.scheduler.stop()
        self.root.destroy()


def run() -> None:
    root = tk.Tk()
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass
    PowerStackApp(root)
    root.mainloop()
