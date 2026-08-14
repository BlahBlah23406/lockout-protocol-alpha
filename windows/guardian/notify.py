"""Local on-screen notifications — the stand-in for `UNUserNotificationCenter` on the Mac.

Windows shows these as a toast from the tray icon. The tray owns the icon handle, so it registers
itself here at startup; before that (or if the tray failed to start) notifications are dropped
rather than raised, exactly as an unauthorised UNUserNotificationCenter request would be.
"""

_notifier = None


def set_notifier(fn) -> None:
    global _notifier
    _notifier = fn


def notify_local(title: str, body: str) -> None:
    if _notifier is None:
        return
    try:
        _notifier(title, body)
    except Exception:
        pass
