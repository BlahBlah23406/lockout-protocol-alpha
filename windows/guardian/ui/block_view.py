"""The full-screen block, in its two accountability levels.

What the block *offers* is the entire difference between the two levels the user picks when
starting a session, so it is worth stating plainly:

    self    "Not now" ends the detour, "I'm on task" overrides it. No passcode. You are being
            interrupted and it is going in the log, but you are the one holding the line.
    locked  "Not now" still works with no passcode — the anti-lockout guarantee (SAFEGUARDS.md)
            is absolute and applies at every level. What "locked" costs is the *override*: to
            keep using the app you need the passcode, and your accountability partner is told.

Both levels always have a working, passcode-free way out of the overlay itself. The difference is
never "you cannot leave", it is "leaving on your own terms is visible and costs something". A
monitor that can genuinely trap someone on their own computer is a bug, not a feature.
"""

import tkinter as tk

from . import theme as T
from ..focus.session import ACC_LOCKED
from ..models.prefs import Prefs


def build(parent, app_name: str, reason: str, on_override, on_quit, focus: bool,
          session=None, on_false_alarm=None):
    prefs = Prefs.shared()
    locked = session is not None and session.accountability == ACC_LOCKED
    # Content-rules blocks (no session) keep the original behaviour: passcode-gated override.
    needs_pin = prefs.pin_set and (locked or session is None)

    root = tk.Frame(parent, bg=T.SPACE)
    root.pack(fill="both", expand=True)

    inner = tk.Frame(root, bg=T.SPACE)
    inner.place(relx=0.5, rely=0.5, anchor="center")

    if session is not None:
        tk.Label(inner, text="OFF TASK", bg=T.SPACE, fg=T.RED, font=T.FONT_HUGE).pack(pady=(0, 10))
        tk.Label(inner, text="YOU SAID YOU WERE:", bg=T.SPACE, fg=T.LILAC,
                 font=("Segoe UI Semibold", 9)).pack()
        tk.Label(inner, text=session.task or "(no task set)", bg=T.SPACE, fg=T.GOLD,
                 font=("Segoe UI Black", 17), wraplength=760,
                 justify="center").pack(pady=(2, 16))
    else:
        tk.Label(inner, text="⊘ ACCESS DENIED", bg=T.SPACE, fg=T.RED,
                 font=T.FONT_HUGE).pack(pady=(0, 18))

    tk.Label(inner, text=app_name.upper(), bg=T.SPACE, fg=T.GOLD,
             font=("Segoe UI Black", 15)).pack()
    tk.Label(inner, text=reason or "not part of the declared task", bg=T.SPACE, fg=T.READOUT,
             font=("Consolas", 12), wraplength=680, justify="center").pack(pady=(6, 20))

    state = {"entry": None}
    wrong = tk.Label(inner, text="", bg=T.SPACE, fg=T.RED, font=("Segoe UI", 9))

    def try_override():
        if not needs_pin:
            on_override()
            return
        pin = state["entry"].get() if state["entry"] else ""
        if prefs.check_pin(pin):
            on_override()
        else:
            wrong.configure(text="Wrong passcode")
            if state["entry"]:
                state["entry"].delete(0, "end")

    if needs_pin:
        tk.Label(inner, text="PASSCODE TO OVERRIDE", bg=T.SPACE, fg=T.LILAC,
                 font=("Segoe UI Semibold", 8)).pack()
        e = T.entry(inner, show="•", width=26)
        e.configure(font=T.FONT_MONO_BIG, justify="center")
        e.pack(pady=(2, 4), ipady=6)
        e.bind("<Return>", lambda _e: try_override())
        state["entry"] = e
        if focus:
            e.after(200, e.focus_force)

    wrong.pack()

    # The compliant exit is listed FIRST and coloured as the primary action: the design should
    # make going back to work the path of least resistance, not the override.
    T.LcarsButton(inner, f"Not now · close {app_name}", on_quit,
                  color=T.ORANGE, width=44).pack(pady=(10, 8))

    override_label = ("Override · keep using it" if needs_pin
                      else f"I'm on task · keep using {app_name}")
    T.LcarsButton(inner, override_label, try_override, color=T.RED, width=44).pack()

    # Experimental: only shown when the user has turned learning on, and only for focus blocks.
    if on_false_alarm is not None and prefs.learning_enabled and session is not None:
        def mark():
            try:
                on_false_alarm()
            finally:
                on_override()
        tk.Button(inner, text="This was a false alarm — it IS part of my task",
                  command=mark, bg=T.SPACE, fg=T.BLUE, relief="flat", bd=0, cursor="hand2",
                  font=("Segoe UI", 9, "underline"), activebackground=T.SPACE,
                  activeforeground=T.BLUE).pack(pady=(12, 0))

    footer = _footer_text(session, needs_pin, app_name)
    tk.Label(inner, text=footer, bg=T.SPACE, fg=T.LILAC, font=("Segoe UI", 8),
             wraplength=620, justify="center").pack(pady=(12, 0))

    tk.Label(root, text="LOCKOUT PROTOCOL · FOCUS MONITOR", bg=T.SPACE, fg=T.LILAC,
             font=("Segoe UI Semibold", 9)).pack(side="bottom", pady=18)
    return root


def _footer_text(session, needs_pin: bool, app_name: str) -> str:
    if session is None:
        return f"Dismiss needs no passcode but closes {app_name}."
    if needs_pin:
        return ("This session is LOCKED. Overriding needs the passcode and your accountability "
                "partner is notified either way. Closing the app needs no passcode.")
    return (f"This session is self-managed — nobody else is told. Overriding is logged and "
            f"counted in your session summary.")
