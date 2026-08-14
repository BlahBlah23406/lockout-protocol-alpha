"""Port of `UI/PledgeView.swift` + its `PledgeController`.

The pledge gate, shown when Windows Settings is brought to the foreground. Friction, not a lock:
"I promise" dismisses it and lets the user proceed; "I cannot" minimises Settings.
"""

import threading
import time
import tkinter as tk

from . import theme as T, tkroot
from ..capture import foreground_app
from ..models.event_log import EventLog

COOLDOWN_SECONDS = 30

PLEDGE_TEXT = (
    "Click “I promise” only if you genuinely commit not to use Settings to undermine "
    "Guardian — or ANY other blocking, filtering, or accountability system you have put in "
    "place (content blockers, DNS or network filters, Family Safety limits, router or browser "
    "restrictions, other accountability apps) — or their ability to execute their functions."
)


class PledgeController:

    _instance = None
    _lock = threading.RLock()

    def __init__(self):
        self._window = None
        self._cooldown_until = 0.0
        self._settings_ids = ()

    @classmethod
    def shared(cls) -> "PledgeController":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @property
    def is_showing(self) -> bool:
        return self._window is not None

    def show(self, settings_ids=()) -> None:
        with self._lock:
            if self._window is not None or time.time() < self._cooldown_until:
                return
        self._settings_ids = settings_ids
        tkroot.run_on_ui(self._build)

    def _build(self):
        root = tkroot.get_root()
        if root is None or self._window is not None:
            return
        w = tk.Toplevel(root)
        w.overrideredirect(True)
        w.configure(bg=T.SPACE)
        width, height = 620, 480
        sw, sh = w.winfo_screenwidth(), w.winfo_screenheight()
        w.geometry(f"{width}x{height}+{(sw - width) // 2}+{(sh - height) // 2}")
        w.attributes("-topmost", True)

        box = tk.Frame(w, bg=T.SPACE)
        box.place(relx=0.5, rely=0.5, anchor="center")
        tk.Frame(box, bg=T.GOLD, width=90, height=22).pack(pady=(0, 14))
        tk.Label(box, text="PAUSE.", bg=T.SPACE, fg=T.ORANGE,
                 font=("Segoe UI Black", 34)).pack(pady=(0, 14))
        tk.Label(box, text=PLEDGE_TEXT, bg=T.SPACE, fg=T.READOUT, font=("Segoe UI", 11),
                 wraplength=540, justify="center").pack(pady=(0, 20))
        T.LcarsButton(box, "I promise", self._swear, color=T.GOLD, width=38).pack(pady=4)
        T.LcarsButton(box, "I cannot — take me back", self._decline,
                      color=T.BLUE, width=38).pack(pady=4)

        self._window = w
        w.lift()
        w.focus_force()

    def _swear(self):
        EventLog.shared().add("[pledge] pledge taken - entered Settings")
        self._dismiss()

    def _decline(self):
        EventLog.shared().add("[pledge] pledge declined - left Settings")
        for identifier in self._settings_ids:
            try:
                foreground_app.hide(identifier)
            except Exception:
                pass
        self._dismiss()

    def _dismiss(self):
        # Brief cooldown so re-focusing Settings doesn't immediately re-pop the pledge.
        self._cooldown_until = time.time() + COOLDOWN_SECONDS
        if self._window is not None:
            try:
                self._window.destroy()
            except tk.TclError:
                pass
        self._window = None
