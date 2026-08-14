"""Port of `Service/Overrides.swift`.

Tracks apps the user has temporarily "overridden" by dismissing a block screen with the passcode.
While an override is active the monitor leaves that app alone — so you aren't re-blocked the
instant you dismiss.
"""

import threading
import time

_lock = threading.RLock()
_until: dict = {}


def grant(identifier: str, seconds: float = 300) -> None:
    """Grant an override for an app (default 5 minutes), e.g. after a correct passcode dismissal."""
    with _lock:
        _until[identifier] = time.time() + seconds


def is_active(identifier: str) -> bool:
    with _lock:
        t = _until.get(identifier)
        if t is None:
            return False
        if t > time.time():
            return True
        _until.pop(identifier, None)
        return False


def clear(identifier: str) -> None:
    with _lock:
        _until.pop(identifier, None)
