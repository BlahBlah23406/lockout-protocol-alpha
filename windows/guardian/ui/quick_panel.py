"""The mini panel: a small, borderless window that drops out of the tray icon.

The Windows counterpart of the macOS menu-bar popover. It exists because the full dashboard is
the wrong shape for the two things people actually do — start a session, and glance at whether
one is running. Opening a 740x600 window with an activity log to answer "am I being watched right
now?" is enough friction that people stop asking.

It anchors itself to the bottom-right above the taskbar rather than following the cursor, so it
lands in the same place every time and can be dismissed by clicking away from it.
"""

import tkinter as tk

from . import theme as T
from .focus_start_view import FocusStartWindow
from .passcode_prompt import require
from ..focus.session import ACC_LOCKED, SessionStore
from ..models.prefs import Prefs

WIDTH = 340
HEIGHT = 300
MARGIN = 12
TASKBAR_ALLOWANCE = 48


class QuickPanel(tk.Toplevel):
    """One instance, reused. `toggle()` is what the tray icon calls."""

    _instance = None

    def __init__(self, master, on_open_dashboard=None):
        super().__init__(master)
        self.prefs = Prefs.shared()
        self.store = SessionStore.shared()
        self.on_open_dashboard = on_open_dashboard

        self.overrideredirect(True)          # no title bar; this is a popover, not a window
        self.configure(bg=T.SPACE, highlightbackground=T.BLUE, highlightthickness=1)
        self.attributes("-topmost", True)
        self.withdraw()

        self._body = tk.Frame(self, bg=T.SPACE)
        self._body.pack(fill="both", expand=True)

        # Clicking anywhere else dismisses it, the way a real popover behaves.
        self.bind("<FocusOut>", lambda _e: self.hide())
        self._tick_job = None

    @classmethod
    def shared(cls, master, on_open_dashboard=None) -> "QuickPanel":
        if cls._instance is None or not cls._instance.winfo_exists():
            cls._instance = QuickPanel(master, on_open_dashboard)
        return cls._instance

    # ---- show / hide -------------------------------------------------------------------

    def toggle(self):
        if self.winfo_viewable():
            self.hide()
        else:
            self.show()

    def show(self):
        self._render()
        x = self.winfo_screenwidth() - WIDTH - MARGIN
        y = self.winfo_screenheight() - HEIGHT - TASKBAR_ALLOWANCE
        self.geometry(f"{WIDTH}x{HEIGHT}+{max(x, 0)}+{max(y, 0)}")
        self.deiconify()
        self.lift()
        self.focus_force()
        self._schedule_tick()

    def hide(self):
        if self._tick_job is not None:
            try:
                self.after_cancel(self._tick_job)
            except Exception:
                pass
            self._tick_job = None
        self.withdraw()

    def _schedule_tick(self):
        """Repaint once a second so the countdown is live while the panel is open — and only
        while it is open, because a hidden panel repainting forever is pure waste."""
        if not self.winfo_viewable():
            return
        self._render()
        self._tick_job = self.after(1000, self._schedule_tick)

    # ---- content -----------------------------------------------------------------------

    def _render(self):
        for w in self._body.winfo_children():
            w.destroy()
        session = self.store.current
        if session is None:
            self._render_idle()
        else:
            self._render_active(session)

    def _render_idle(self):
        head = tk.Frame(self._body, bg=T.SPACE)
        head.pack(fill="x", padx=14, pady=(14, 6))
        tk.Frame(head, bg=T.LILAC, width=26, height=14).pack(side="left", padx=(0, 8))
        tk.Label(head, text="NO SESSION", bg=T.SPACE, fg=T.LILAC,
                 font=("Segoe UI Black", 12)).pack(side="left")

        tk.Label(self._body, text="Nothing is being watched. No screenshots are taken until you "
                                  "start a session.",
                 bg=T.SPACE, fg=T.READOUT, font=("Segoe UI", 9), wraplength=300,
                 justify="left").pack(anchor="w", padx=14, pady=(0, 10))

        last = self.prefs.last_task
        if last:
            tk.Label(self._body, text="LAST TIME", bg=T.SPACE, fg=T.BLUE,
                     font=("Consolas", 8, "bold")).pack(anchor="w", padx=14)
            tk.Label(self._body, text=last, bg=T.SPACE, fg=T.GOLD, font=("Consolas", 9),
                     wraplength=300, justify="left").pack(anchor="w", padx=14, pady=(0, 10))
            T.LcarsButton(self._body, "Start that again", self._restart_last,
                          color=T.GOLD).pack(fill="x", padx=14, pady=(0, 6))

        T.LcarsButton(self._body, "New focus session…", self._new_session,
                      color=T.ORANGE).pack(fill="x", padx=14, pady=(0, 6))
        self._dashboard_link()

    def _render_active(self, session):
        head = tk.Frame(self._body, bg=T.SPACE)
        head.pack(fill="x", padx=14, pady=(14, 4))
        colour = T.RED if session.accountability == ACC_LOCKED else T.READOUT
        tk.Frame(head, bg=colour, width=26, height=14).pack(side="left", padx=(0, 8))
        tk.Label(head, text="LOCKED" if session.accountability == ACC_LOCKED else "IN FOCUS",
                 bg=T.SPACE, fg=colour, font=("Segoe UI Black", 12)).pack(side="left")
        if self.prefs.dry_run:
            tk.Label(head, text=" TEST ", bg=T.GOLD, fg=T.SPACE,
                     font=("Consolas", 7, "bold")).pack(side="left", padx=6)

        tk.Label(self._body, text=session.task, bg=T.SPACE, fg=T.GOLD, font=("Consolas", 10),
                 wraplength=300, justify="left").pack(anchor="w", padx=14, pady=(2, 8))

        left = session.remaining_seconds
        time_text = ("open-ended" if left is None
                     else f"{int(left // 60)}m {int(left % 60):02d}s left")
        rows = [
            ("TIME", time_text),
            ("CHECKS", f"{session.checks} ({session.off_task_count} off-task)"),
            ("EVERY", f"{session.interval_seconds}s"),
            ("APPS", f"{len(session.watchlist(self.prefs.monitored_apps))} watched"),
        ]
        if session.override_count:
            rows.append(("OVERRIDES", str(session.override_count)))

        panel = T.ReadoutPanel(self._body)
        panel.pack(fill="x", padx=14, pady=(0, 8))
        for label, value in rows:
            r = tk.Frame(panel, bg=T.PANEL)
            r.pack(fill="x", pady=1)
            tk.Label(r, text=label, bg=T.PANEL, fg=T.BLUE, font=("Consolas", 8, "bold"),
                     width=10, anchor="w").pack(side="left")
            tk.Label(r, text=value, bg=T.PANEL, fg=T.READOUT, font=("Consolas", 8),
                     anchor="w").pack(side="left", fill="x", expand=True)

        T.LcarsButton(self._body, "End session", self._end_session, color=T.RED).pack(
            fill="x", padx=14, pady=(0, 6))
        self._dashboard_link()

    def _dashboard_link(self):
        tk.Button(self._body, text="Open full dashboard", command=self._open_dashboard,
                  bg=T.SPACE, fg=T.BLUE, relief="flat", bd=0, cursor="hand2",
                  font=("Segoe UI", 8), activebackground=T.SPACE,
                  activeforeground=T.BLUE).pack(side="bottom", pady=(0, 10))

    # ---- actions -----------------------------------------------------------------------

    def _new_session(self):
        self.hide()
        FocusStartWindow(self.master)

    def _restart_last(self):
        """One click to run the same session again — same task, same settings as last time."""
        self.hide()
        win = FocusStartWindow(self.master)
        win.after(200, win.start_now)

    def _end_session(self):
        session = self.store.current
        if session is None:
            return
        # A locked session holds its own exit. This is the passcode's real job — not stopping you
        # from using the computer, but stopping you from quietly cancelling the commitment.
        if session.requires_passcode_to_end() and not require(self, "end this locked session"):
            return
        self.store.end("ended by user")
        from ..service.monitor_service import MonitorService
        MonitorService.shared().stop()
        self._render()

    def _open_dashboard(self):
        self.hide()
        if self.on_open_dashboard:
            self.on_open_dashboard()
