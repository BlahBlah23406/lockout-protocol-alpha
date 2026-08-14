"""Port of `UI/BlockView.swift`.

The full-screen block screen content. Red-alert "ACCESS DENIED" with the reason. Two ways out:
  * Dismiss — no passcode needed, but it CLOSES the offending app (the compliant exit).
  * Override — keep using the app; requires the passcode when one is set.

Both exits always work: an always-available, passcode-free Dismiss is the anti-lockout guarantee
(see SAFEGUARDS.md) and must stay.
"""

import tkinter as tk

from . import theme as T
from ..models.prefs import Prefs


def build(parent, app_name: str, reason: str, on_override, on_quit, focus: bool):
    prefs = Prefs.shared()
    root = tk.Frame(parent, bg=T.SPACE)
    root.pack(fill="both", expand=True)

    inner = tk.Frame(root, bg=T.SPACE)
    inner.place(relx=0.5, rely=0.5, anchor="center")

    tk.Label(inner, text="⊘ ACCESS DENIED", bg=T.SPACE, fg=T.RED,
             font=T.FONT_HUGE).pack(pady=(0, 18))

    tk.Label(inner, text=app_name.upper(), bg=T.SPACE, fg=T.GOLD,
             font=("Segoe UI Black", 18)).pack()
    tk.Label(inner, text=reason or "guideline violation", bg=T.SPACE, fg=T.READOUT,
             font=("Consolas", 12), wraplength=680, justify="center").pack(pady=(6, 22))

    state = {"entry": None}

    def try_override():
        if not prefs.pin_set:
            on_override()
            return
        pin = state["entry"].get() if state["entry"] else ""
        if prefs.check_pin(pin):
            on_override()
        else:
            wrong.configure(text="Wrong passcode")
            if state["entry"]:
                state["entry"].delete(0, "end")

    if prefs.pin_set:
        e = T.entry(inner, show="•", width=26)
        e.configure(font=T.FONT_MONO_BIG, justify="center")
        e.pack(pady=(0, 4), ipady=6)
        e.bind("<Return>", lambda _e: try_override())
        state["entry"] = e
        if focus:
            e.after(200, e.focus_force)

    wrong = tk.Label(inner, text="", bg=T.SPACE, fg=T.RED, font=("Segoe UI", 9))
    wrong.pack()

    T.LcarsButton(inner, f"Override · keep using {app_name}", try_override,
                  color=T.ORANGE, width=42).pack(pady=(10, 8))
    T.LcarsButton(inner, f"Dismiss · close {app_name}", on_quit,
                  color=T.RED, width=42).pack()
    tk.Label(inner, text=f"Dismiss needs no passcode but closes {app_name}.",
             bg=T.SPACE, fg=T.LILAC, font=("Segoe UI", 8)).pack(pady=(8, 0))

    tk.Label(root, text="GUARDIAN · ACCOUNTABILITY MONITOR", bg=T.SPACE, fg=T.LILAC,
             font=("Segoe UI Semibold", 9)).pack(side="bottom", pady=18)
    return root
