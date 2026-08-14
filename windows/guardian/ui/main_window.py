"""Main application window for Guardian on Windows.

Mirrors `RootView.swift`: gates opening the dashboard behind the passcode (when set)
and hides to system tray on close instead of exiting.
"""

import tkinter as tk

from . import theme as T
from .dashboard_view import DashboardFrame
from ..models.prefs import Prefs


class MainWindow(tk.Toplevel):

    def __init__(self, master=None):
        super().__init__(master)
        self.prefs = Prefs.shared()
        self.title("Guardian — Accountability Monitor")
        self.configure(bg=T.SPACE)
        self.geometry("740x600")
        self.minsize(720, 560)
        T.apply_ttk_dark(self)

        self.unlocked = not self.prefs.pin_set
        self.protocol("WM_DELETE_WINDOW", self.hide_to_tray)

        self._render()

    def show_dashboard(self):
        """Re-open / show the window. Requires passcode if locked."""
        self.deiconify()
        self.lift()
        self.focus_force()
        if self.prefs.pin_set and not self.unlocked:
            self._render()

    def hide_to_tray(self):
        """Closing the window hides it to tray rather than quitting Guardian."""
        self.withdraw()
        # Reset unlocked state so reopening requires the passcode again (matches macOS LockActivity)
        if self.prefs.pin_set:
            self.unlocked = False

    def _render(self):
        for w in self.winfo_children():
            w.destroy()

        if self.prefs.pin_set and not self.unlocked:
            self._build_lock_view()
        else:
            DashboardFrame(self, on_close=self.hide_to_tray).pack(fill="both", expand=True)

    def _build_lock_view(self):
        box = tk.Frame(self, bg=T.SPACE)
        box.place(relx=0.5, rely=0.5, anchor="center")

        tk.Frame(box, bg=T.ORANGE, width=90, height=26).pack(pady=(0, 14))
        tk.Label(box, text="GUARDIAN", bg=T.SPACE, fg=T.GOLD,
                 font=("Segoe UI Black", 32)).pack(pady=(0, 6))
        tk.Label(box, text="Enter passcode to unlock", bg=T.SPACE, fg=T.LILAC,
                 font=("Segoe UI", 11)).pack(pady=(0, 18))

        e = T.entry(box, show="•", width=28)
        e.configure(font=T.FONT_MONO_BIG, justify="center")
        e.pack(pady=(0, 6), ipady=6)

        wrong = tk.Label(box, text="", bg=T.SPACE, fg=T.RED, font=("Segoe UI", 9))
        wrong.pack()

        def check(_event=None):
            if self.prefs.check_pin(e.get()):
                self.unlocked = True
                self._render()
            else:
                wrong.configure(text="Wrong passcode")
                e.delete(0, "end")

        e.bind("<Return>", check)
        T.LcarsButton(box, "Unlock", check, color=T.ORANGE, width=28).pack(pady=(12, 0))
        e.after(150, e.focus_force)
