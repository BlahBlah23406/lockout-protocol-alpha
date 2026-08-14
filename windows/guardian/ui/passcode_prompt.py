"""A modal passcode challenge, used wherever an action is gated.

The Mac app inlined this in three places (the lock gate, the block screen, the menu-bar
stop/quit confirm); on Windows the same three places plus "changing settings" all share it.
"""

import tkinter as tk

from . import theme as T
from ..models.prefs import Prefs


def require(parent, action_label: str) -> bool:
    """Blocks until the user enters the passcode or cancels. True when allowed through.

    Returns True immediately when no passcode is set — the app is usable without one, exactly as on
    the Mac, where an unset passcode means the gate simply isn't there.
    """
    prefs = Prefs.shared()
    if not prefs.pin_set:
        return True

    win = tk.Toplevel(parent)
    win.title("Guardian")
    win.configure(bg=T.SPACE)
    win.geometry("380x210")
    win.attributes("-topmost", True)
    win.transient(parent)
    win.resizable(False, False)

    result = {"ok": False}

    tk.Label(win, text="GUARDIAN", bg=T.SPACE, fg=T.GOLD,
             font=("Segoe UI Black", 18)).pack(pady=(20, 4))
    tk.Label(win, text=f"Enter passcode to {action_label}", bg=T.SPACE, fg=T.LILAC,
             font=("Segoe UI", 9)).pack()

    entry = T.entry(win, show="•", width=24)
    entry.configure(justify="center", font=T.FONT_MONO_BIG)
    entry.pack(pady=12, ipady=5)

    wrong = tk.Label(win, text="", bg=T.SPACE, fg=T.RED, font=("Segoe UI", 8))
    wrong.pack()

    def check(_event=None):
        if prefs.check_pin(entry.get()):
            result["ok"] = True
            win.destroy()
        else:
            wrong.configure(text="Wrong passcode")
            entry.delete(0, "end")

    entry.bind("<Return>", check)
    row = tk.Frame(win, bg=T.SPACE)
    row.pack(pady=8)
    T.LcarsButton(row, "Unlock", check, color=T.ORANGE).pack(side="left", padx=4)
    T.LcarsButton(row, "Cancel", win.destroy, color=T.LILAC).pack(side="left", padx=4)

    entry.after(100, entry.focus_force)
    win.grab_set()
    parent.wait_window(win)
    return result["ok"]
