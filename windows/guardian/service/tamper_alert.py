"""Port of `Service/TamperAlert.swift`.

One place to raise a "someone is tampering with Guardian" alert. As on macOS and Android, the real
enforcement is social: the moment a defense is touched, the accountability contact is pushed. Fires
an ntfy push + a local Windows notification, de-duped so one tamper action doesn't spam.
"""

import platform
import threading
import time
from datetime import datetime

from ..models.event_log import EventLog
from ..models.prefs import Prefs
from ..notify import notify_local
from ..push import pusher

_last_at = None
_lock = threading.RLock()
DEDUPE_SECONDS = 60


def raise_alert(reason: str, force: bool = False) -> None:
    global _last_at
    with _lock:
        if not force and _last_at is not None and time.time() - _last_at < DEDUPE_SECONDS:
            return
        _last_at = time.time()

    EventLog.shared().add(f"[TAMPER] {reason}")

    prefs = Prefs.shared()
    title = "[Guardian] Tamper alert"
    host = platform.node() or "this PC"
    body = f"{reason}\n\nDevice: {host}\n{datetime.now()}"

    # Local notification (visible on-screen even if push is down).
    notify_local(title, reason)

    # Push to the accountability contact, off the caller's thread.
    cfg = pusher.Config(prefs.push_enabled, prefs.ntfy_server, prefs.ntfy_topic)

    def _send():
        err = pusher.send(cfg, title, body)
        if err:
            EventLog.shared().add(f"[warn] tamper push failed: {err}")

    threading.Thread(target=_send, name="guardian-tamper-push", daemon=True).start()
