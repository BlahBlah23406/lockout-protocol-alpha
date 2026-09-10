"""The main dashboard: session state on top, controls below, activity log at the bottom."""

import threading
import tkinter as tk
from tkinter import ttk

from . import theme as T
from .app_picker_view import AppPickerWindow
from .focus_start_view import FocusStartWindow
from .guidelines_view import GuidelinesWindow
from .passcode_prompt import require
from .settings_view import SettingsWindow
from ..capture import screen_capturer
from ..focus.session import ACC_LOCKED, SessionStore
from ..models.event_log import EventLog
from ..models.prefs import Prefs
from ..service import persistence
from ..service.monitor_service import MonitorService


class DashboardFrame(tk.Frame):

    def __init__(self, master, on_close=None):
        super().__init__(master, bg=T.SPACE)
        self.prefs = Prefs.shared()
        self.monitor = MonitorService.shared()
        self.sessions = SessionStore.shared()
        self.event_log = EventLog.shared()
        self.on_close = on_close

        self.screen_rec_ok = False
        self._build_ui()

        # Subscribe to live updates
        self.prefs.subscribe(self._update_readouts)
        self.monitor.subscribe(self._update_readouts)
        self.sessions.subscribe(self._update_readouts)
        self.event_log.subscribe(self._on_log_entry)

        self._start_screen_rec_poll()
        self._update_readouts()
        self._reload_full_log()

    def _build_ui(self):
        T.LcarsHeader(self, "Lockout Protocol", "Focus Monitor").pack(
            fill="x", padx=16, pady=(14, 10))

        # ---- Top panels grid (Status + Defenses) ----
        top_grid = tk.Frame(self, bg=T.SPACE)
        top_grid.pack(fill="x", padx=16, pady=(0, 10))

        # Left: Status panel
        self.status_box = T.ReadoutPanel(top_grid)
        self.status_box.pack(side="left", fill="both", expand=True, padx=(0, 6))

        # Right: Defenses panel
        self.defenses_box = T.ReadoutPanel(top_grid)
        self.defenses_box.pack(side="right", fill="both", expand=True, padx=(6, 0))

        # ---- Control buttons row 1 ----
        btn_row1 = tk.Frame(self, bg=T.SPACE)
        btn_row1.pack(fill="x", padx=16, pady=(0, 6))

        self.btn_start_stop = T.LcarsButton(btn_row1, "Start focus session",
                                            self._toggle_session, color=T.ORANGE)
        self.btn_start_stop.pack(side="left", fill="x", expand=True, padx=(0, 4))

        self.btn_arm_test = T.LcarsButton(btn_row1, "Test Mode", self._toggle_arm_test, color=T.GOLD)
        self.btn_arm_test.pack(side="left", fill="x", expand=True, padx=(4, 0))

        # ---- Navigation buttons row 2 ----
        btn_row2 = tk.Frame(self, bg=T.SPACE)
        btn_row2.pack(fill="x", padx=16, pady=(0, 10))

        T.LcarsButton(btn_row2, "Apps", self._open_apps, color=T.BLUE).pack(side="left", fill="x", expand=True, padx=(0, 4))
        T.LcarsButton(btn_row2, "Guidelines", self._open_guidelines, color=T.LILAC).pack(side="left", fill="x", expand=True, padx=(2, 2))
        T.LcarsButton(btn_row2, "Settings", self._open_settings, color=T.BLUE).pack(side="left", fill="x", expand=True, padx=(4, 0))

        # ---- Activity log ----
        log_header = tk.Frame(self, bg=T.SPACE)
        log_header.pack(fill="x", padx=16, pady=(0, 4))

        tk.Label(log_header, text="ACTIVITY LOG", bg=T.SPACE, fg=T.GOLD,
                 font=("Segoe UI Black", 9)).pack(side="left")
        tk.Button(log_header, text="Clear", command=self._clear_log, bg=T.SPACE, fg=T.BLUE,
                  relief="flat", bd=0, font=("Segoe UI", 8), cursor="hand2",
                  activebackground=T.SPACE).pack(side="right")

        log_panel = T.ReadoutPanel(self)
        log_panel.pack(fill="both", expand=True, padx=16, pady=(0, 14))

        self.log_text = tk.Text(log_panel, bg=T.PANEL, fg=T.READOUT, insertbackground=T.READOUT,
                                relief="flat", font=T.FONT_MONO, wrap="none", bd=0,
                                highlightthickness=0, state="disabled")
        bar_y = tk.Scrollbar(log_panel, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=bar_y.set)

        self.log_text.pack(side="left", fill="both", expand=True)
        bar_y.pack(side="right", fill="y")

    # ---- Live updates ------------------------------------------------------------------

    def _start_screen_rec_poll(self):
        def poll():
            val = screen_capturer.has_permission()
            self.after(0, lambda: self._on_screen_rec_updated(val))
        threading.Thread(target=poll, name="guardian-rec-poll", daemon=True).start()
        self.after(3000, self._start_screen_rec_poll)

    def _on_screen_rec_updated(self, ok: bool):
        if self.screen_rec_ok != ok:
            self.screen_rec_ok = ok
            self._update_readouts()

    def _update_readouts(self):
        try:
            self._render_status()
            self._render_defenses()
            self._render_buttons()
        except tk.TclError:
            pass

    def _render_status(self):
        for w in self.status_box.winfo_children():
            w.destroy()

        session = self.sessions.current
        dry = self.prefs.dry_run

        if session is None:
            rows = [
                ("SESSION", "none - nothing is being watched", T.LILAC),
                ("PRIVACY", "no screenshots are taken while idle", T.READOUT),
                ("DEFAULTS", f"{len(self.prefs.monitored_apps)} app(s) on the watchlist", T.READOUT),
                ("PROVIDER", f"{self.prefs.provider_model or 'not set'}", T.BLUE),
                ("ACCESS", "passcode set" if self.prefs.pin_set else "no passcode",
                 T.READOUT if self.prefs.pin_set else T.LILAC),
                ("ALERTS", f"ntfy -> {self.prefs.ntfy_topic}" if self.prefs.push_enabled else "off",
                 T.LILAC),
            ]
        else:
            locked = session.accountability == ACC_LOCKED
            left = session.remaining_seconds
            when = "open-ended" if left is None else f"{int(left // 60)}m left"
            rows = [
                ("TASK", session.task[:56] or "(none)", T.GOLD),
                ("MODE", "LOCKED - passcode to override" if locked else "self-managed",
                 T.RED if locked else T.READOUT),
                ("TIME", when + ("  [TEST - nothing is blocked]" if dry else ""),
                 T.GOLD if dry else T.READOUT),
                ("CHECKS", f"{session.checks} run, {session.off_task_count} off-task, "
                           f"{session.override_count} override(s)", T.READOUT),
                ("EVERY", f"{session.interval_seconds}s", T.READOUT),
                ("WATCHING", f"{len(session.watchlist(self.prefs.monitored_apps))} app(s)",
                 T.READOUT),
                ("ACTIVITY", self.monitor.status, T.READOUT),
                ("PROVIDER", self.prefs.provider_model or "not set", T.BLUE),
            ]

        for label, val, col in rows:
            r = tk.Frame(self.status_box, bg=T.PANEL)
            r.pack(fill="x", anchor="w", pady=1)
            tk.Label(r, text=label, bg=T.PANEL, fg=T.BLUE, font=("Consolas", 8, "bold"),
                     width=10, anchor="w").pack(side="left")
            tk.Label(r, text=val, bg=T.PANEL, fg=col, font=("Consolas", 8),
                     anchor="w").pack(side="left", fill="x", expand=True)

    def _render_defenses(self):
        for w in self.defenses_box.winfo_children():
            w.destroy()

        tk.Label(self.defenses_box, text="DEFENSES", bg=T.PANEL, fg=T.GOLD,
                 font=("Segoe UI Black", 9)).pack(anchor="w", pady=(0, 4))

        keep_alive_on = persistence.KeepAliveAgent.is_active()
        login_on = persistence.LaunchAtLogin.is_enabled()
        pledge_on = self.prefs.pledge_on_settings
        self_heal_on = self.prefs.monitoring_enabled

        def_rows = [
            ("SCREEN CAP", self.screen_rec_ok, "granted", "OFF - can't see screen", True, False),
            ("KEEP-ALIVE", keep_alive_on, "on - relaunches if quit", "off", False, True),
            ("LOGIN ITEM", login_on, "on", "off", False, False),
            ("PLEDGE", pledge_on, "on (Windows Settings)", "off", False, False),
            ("SELF-HEAL", self_heal_on, "watchdog + alerts armed", "monitoring off", False, False),
        ]

        for label, active, on_txt, off_txt, warn, gold in def_rows:
            col = (T.GOLD if gold else T.READOUT) if active else (T.RED if warn else T.LILAC)
            marker = "● " if active else "○ "
            txt = marker + (on_txt if active else off_txt)

            r = tk.Frame(self.defenses_box, bg=T.PANEL)
            r.pack(fill="x", anchor="w", pady=1)
            tk.Label(r, text=label, bg=T.PANEL, fg=T.BLUE, font=("Consolas", 8, "bold"),
                     width=11, anchor="w").pack(side="left")
            tk.Label(r, text=txt, bg=T.PANEL, fg=col, font=("Consolas", 8),
                     anchor="w").pack(side="left", fill="x", expand=True)

    def _render_buttons(self):
        if self.sessions.is_active:
            self.btn_start_stop.configure(text="END SESSION", bg=T.RED, activebackground=T.RED)
        else:
            self.btn_start_stop.configure(text="START FOCUS SESSION", bg=T.ORANGE,
                                          activebackground=T.ORANGE)

        if self.prefs.dry_run:
            self.btn_arm_test.configure(text="ARM (TEST MODE ON)", bg=T.GOLD, activebackground=T.GOLD)
        else:
            self.btn_arm_test.configure(text="TEST MODE (ARMED)", bg=T.RED, activebackground=T.RED)

    # ---- Actions -----------------------------------------------------------------------

    def _toggle_session(self):
        session = self.sessions.current
        if session is None:
            FocusStartWindow(self.winfo_toplevel())
            return
        # Ending a locked session early costs the passcode.
        if session.requires_passcode_to_end() and not require(self, "end this locked session"):
            return
        self.sessions.end("ended by user")
        self.monitor.stop()
        self._update_readouts()

    def _toggle_arm_test(self):
        self.prefs.dry_run = not self.prefs.dry_run

    def _open_apps(self):
        AppPickerWindow(self.winfo_toplevel())

    def _open_guidelines(self):
        GuidelinesWindow(self.winfo_toplevel())

    def _open_settings(self):
        if require(self, "open Settings"):
            SettingsWindow(self.winfo_toplevel())

    def _clear_log(self):
        self.event_log.clear()

    def _reload_full_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        for e in self.event_log.entries:
            self.log_text.insert("end", self.event_log.formatted(e) + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _on_log_entry(self, entry):
        def update():
            try:
                if entry is None:
                    self._reload_full_log()
                else:
                    self.log_text.configure(state="normal")
                    self.log_text.insert("end", self.event_log.formatted(entry) + "\n")
                    self.log_text.see("end")
                    self.log_text.configure(state="disabled")
            except tk.TclError:
                pass
        self.after(0, update)
