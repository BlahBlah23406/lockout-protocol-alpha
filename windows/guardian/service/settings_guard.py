"""Port of `Service/SettingsGuard.swift`.

Watches which app comes to the foreground and raises the pledge window when the user opens Windows
Settings — the place where Guardian's screen-capture permission, its startup entry, and the app
itself can be removed (Privacy & security, Startup apps, Installed apps). Non-blocking: after
pledging, the user can still use Settings.

macOS got this for free from `NSWorkspace.didActivateApplicationNotification`; here it's a one-second
poll of the foreground app, which is cheap and needs no hook.
"""

import threading

from ..capture import foreground_app
from ..models.prefs import Prefs
from ..ui.pledge_view import PledgeController

POLL = 1.0

# Windows Settings and the classic Control Panel host every page the Mac app was guarding:
# app permissions, startup apps, and installed-apps/uninstall.
SETTINGS_IDS = {"systemsettings.exe", "control.exe"}


class SettingsGuard:

    _instance = None
    _lock = threading.RLock()

    def __init__(self):
        self._thread = None
        self._stop = threading.Event()
        self._last = None

    @classmethod
    def shared(cls) -> "SettingsGuard":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def start(self) -> None:
        with self._lock:
            if self._thread is not None:
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="guardian-settings",
                                            daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread = None

    def _loop(self) -> None:
        while not self._stop.wait(POLL):
            try:
                self._handle(foreground_app.identifier())
            except Exception:
                pass

    def _handle(self, identifier) -> None:
        previous, self._last = self._last, identifier
        if identifier == previous:
            return                          # only react to the transition, not to sitting there
        if not Prefs.shared().pledge_on_settings:
            return
        if identifier in SETTINGS_IDS:
            PledgeController.shared().show(settings_ids=SETTINGS_IDS)
