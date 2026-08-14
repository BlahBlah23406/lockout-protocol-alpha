"""The single hidden Tk root every window hangs off, plus a way to get onto the UI thread.

Tk is not thread-safe and the monitor loop runs on a background thread, so everything that touches
a widget goes through `run_on_ui`. This is the Tk equivalent of the Mac app's `@MainActor`.
"""

import queue
import threading

_root = None
_pending = queue.Queue()
_lock = threading.Lock()


def set_root(root) -> None:
    global _root
    with _lock:
        _root = root
    _drain()


def get_root():
    return _root


def run_on_ui(fn) -> None:
    """Schedule `fn` on the Tk thread. Safe to call before the root exists."""
    root = _root
    if root is None:
        _pending.put(fn)
        return
    try:
        root.after(0, fn)
    except Exception:
        pass


def _drain() -> None:
    while True:
        try:
            fn = _pending.get_nowait()
        except queue.Empty:
            return
        run_on_ui(fn)
