"""Port of `Service/TamperGuard.swift`.

Watches for the Windows ways Guardian gets defeated and reacts, mirroring the Mac/Android tamper
layer:

 1. **Screen capture lost** — Guardian's only way of seeing anything. If capture worked and now
    doesn't while monitoring is enabled, fire a tamper alert. This covers the Windows 11 privacy
    toggle for programmatic graphics capture as well as capture simply failing, and is the analogue
    of macOS Screen Recording being revoked / Android accessibility being turned off.
 2. **Keep-alive removed** — the Windows equivalent of `launchctl bootout`-ing the KeepAlive agent:
    the watchdog process killed, or its `Run` entry deleted, while the setting is still on. Alert
    and put it back.
 3. **Monitor watchdog** — if monitoring should be running but the loop died, restart it.

A user with admin rights can always kill a process or edit their own registry; this can't prevent
that, but it makes it loud and self-healing instead of a silent bypass.
"""

import threading

from ..capture import screen_capturer, screen_state
from ..models.event_log import EventLog
from ..models.prefs import Prefs
from . import persistence, tamper_alert
from .monitor_service import MonitorService

INTERVAL = 15


class TamperGuard:

    _instance = None
    _lock = threading.RLock()

    def __init__(self):
        self._timer = None
        self._stop = threading.Event()
        self._prefs = Prefs.shared()
        # Consecutive "capture looks gone" readings taken while the screen was visible. Debounced so
        # a single capture hiccup doesn't read as a revoke.
        self._missed_capture_checks = 0
        self._keepalive_was_up = False

    @classmethod
    def shared(cls) -> "TamperGuard":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def start(self) -> None:
        with self._lock:
            if self._timer is not None:
                return
            self._stop.clear()
            self._timer = threading.Thread(target=self._loop, name="guardian-tamper", daemon=True)
            self._timer.start()

    def stop(self) -> None:
        self._stop.set()
        self._timer = None

    def _loop(self) -> None:
        self._check()                       # seed the baseline immediately, then poll
        while not self._stop.wait(INTERVAL):
            try:
                self._check()
            except Exception as e:
                EventLog.shared().add(f"[warn] tamper check failed: {e}")

    def _check(self) -> None:
        prefs = self._prefs

        # 1. Screen-capture transition tracking. Only meaningful while the screen is actually on:
        #    with the display asleep or the session locked a capture is meaningless, which is
        #    exactly the false positive that used to alert every time the screen went off.
        if screen_state.is_visible():
            granted = screen_capturer.has_permission()
            if prefs.monitoring_enabled:
                if prefs.screen_capture_granted and not granted:
                    # Require two consecutive misses so a momentary hiccup can't masquerade as
                    # tampering. A real revoke persists and alerts 15s later.
                    self._missed_capture_checks += 1
                    if self._missed_capture_checks >= 2:
                        prefs.screen_capture_granted = False
                        self._missed_capture_checks = 0
                        why = ("screen-capture permission was turned off in Windows privacy "
                               "settings" if screen_capturer.capture_consent_denied()
                               else "Guardian can no longer capture the screen")
                        tamper_alert.raise_alert(
                            f"Guardian's screen capture stopped working - {why}. "
                            "It can no longer see the screen.", force=True)
                elif granted:
                    self._missed_capture_checks = 0
                    if not prefs.screen_capture_granted:
                        prefs.screen_capture_granted = True
            elif granted:
                prefs.screen_capture_granted = True
        else:
            # Screen is off/locked — the reading is meaningless, so don't hold a miss against it.
            self._missed_capture_checks = 0

        # 2. Keep-alive removed while it is supposed to be on.
        if prefs.keep_alive:
            up = persistence.keepalive_running()
            registered = persistence.LaunchAtLogin.is_enabled() or \
                persistence._get_run_value(persistence.KEEPALIVE_VALUE) is not None
            if self._keepalive_was_up and not up:
                tamper_alert.raise_alert(
                    "Guardian's keep-alive watchdog was killed - it is being restarted.")
            if not up or not registered:
                persistence.apply()
            self._keepalive_was_up = persistence.keepalive_running()

        # 3. Watchdog: keep the monitor alive.
        if prefs.monitoring_enabled and not MonitorService.shared().is_running:
            EventLog.shared().add("[heal] watchdog restarting monitor")
            MonitorService.shared().start()
