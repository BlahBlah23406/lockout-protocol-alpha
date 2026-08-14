"""Port of `Models/EventLog.swift`.

Observable activity log shown live in the dashboard: each screenshot + AI verdict gets a
timestamped line. The Mac app kept the log in memory only; here it is also appended to a file
under LocalAppData, because on Windows the dashboard is far more often closed than open and a log
you can read after the fact is what makes TEST mode useful.
"""

import threading
import time
from datetime import datetime

from ..paths import LOG_FILE

MAX_ENTRIES = 500


class Entry:
    __slots__ = ("time", "text")

    def __init__(self, t: float, text: str):
        self.time = t
        self.text = text


class EventLog:
    _instance = None
    _lock = threading.RLock()

    def __init__(self):
        self.entries: list[Entry] = []
        self._listeners = []

    @classmethod
    def shared(cls) -> "EventLog":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def subscribe(self, fn):
        self._listeners.append(fn)

    def add(self, text: str) -> None:
        with self._lock:
            e = Entry(time.time(), text)
            self.entries.append(e)
            if len(self.entries) > MAX_ENTRIES:
                del self.entries[: len(self.entries) - MAX_ENTRIES]
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"{datetime.fromtimestamp(e.time):%Y-%m-%d %H:%M:%S}  {text}\n")
        except Exception:
            pass
        for fn in list(self._listeners):
            try:
                fn(e)
            except Exception:
                pass

    def clear(self) -> None:
        with self._lock:
            self.entries.clear()
        for fn in list(self._listeners):
            try:
                fn(None)
            except Exception:
                pass

    @staticmethod
    def formatted(e: Entry) -> str:
        return f"{datetime.fromtimestamp(e.time):%H:%M:%S}  {e.text}"


def log(text: str) -> None:
    """Convenience so background threads can log without holding a reference."""
    EventLog.shared().add(text)
