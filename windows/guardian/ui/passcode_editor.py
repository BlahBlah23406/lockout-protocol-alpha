"""Port of `UI/PasscodeEditor.swift`.

Set / change / remove the access + override passcode. Changing or removing requires the current
passcode when one is already set.
"""

import tkinter as tk

from . import theme as T
from ..models.prefs import Prefs


class PasscodeEditor(tk.Frame):

    def __init__(self, master):
        super().__init__(master, bg=T.PANEL)
        self.prefs = Prefs.shared()
        self._build()

    def _build(self):
        for w in self.winfo_children():
            w.destroy()

        self.current = None
        if self.prefs.pin_set:
            self.current = self._field("Current passcode")
        self.new1 = self._field("New passcode")
        self.new2 = self._field("Confirm new passcode")

        row = tk.Frame(self, bg=T.PANEL)
        row.pack(anchor="w", pady=(8, 0))
        T.LcarsButton(row, "Update" if self.prefs.pin_set else "Set passcode",
                      self._save, color=T.ORANGE).pack(side="left", padx=(0, 8))
        if self.prefs.pin_set:
            T.LcarsButton(row, "Remove", self._remove, color=T.RED).pack(side="left")

        self.message = tk.Label(self, text="", bg=T.PANEL, fg=T.READOUT, font=("Segoe UI", 8))
        self.message.pack(anchor="w", pady=(6, 0))

    def _field(self, label):
        tk.Label(self, text=label, bg=T.PANEL, fg=T.BLUE,
                 font=("Segoe UI", 8)).pack(anchor="w", pady=(4, 1))
        e = T.entry(self, show="•", width=32)
        e.pack(anchor="w", ipady=3)
        return e

    def _fail(self, msg):
        self.message.configure(text=msg, fg=T.RED)

    def _succeed(self, msg):
        self._build()
        self.message.configure(text=msg, fg=T.READOUT)

    def _save(self):
        if self.prefs.pin_set and not self.prefs.check_pin(self.current.get()):
            self._fail("Current passcode is wrong")
            return
        new1, new2 = self.new1.get(), self.new2.get()
        if not new1:
            self._fail("Enter a new passcode")
            return
        if new1 != new2:
            self._fail("New passcodes don't match")
            return
        self.prefs.set_pin(new1)
        self._succeed("Passcode saved")

    def _remove(self):
        if not self.prefs.check_pin(self.current.get()):
            self._fail("Current passcode is wrong")
            return
        self.prefs.clear_pin()
        self._succeed("Passcode removed")
