"""Port of `Service/MonitorService.swift`.

The always-on heart of Guardian. Runs a response-driven loop on a background thread: when a
monitored app is in the foreground it grabs a screenshot, classifies it with the Ollama vision
model, and enforces blocks + push alerts. Cadence, safety rules and log wording follow the Mac
original line for line.
"""

import threading
import time
from datetime import datetime

from ..ai import frame_quality
from ..ai.ollama_client import OllamaClient
from ..capture import foreground_app, screen_capturer, screen_state
from ..models.event_log import EventLog
from ..models.prefs import Prefs
from ..notify import notify_local
from ..push import pusher
from . import overrides
from .block_controller import BlockController

# Cadence (mirrors the Mac/Android apps): a small floor between back-to-back checks while on a
# monitored app, and a lazier poll when nothing monitored is on screen.
MIN_GAP = 1.2
IDLE_POLL = 2.5
ALERT_THROTTLE = 10 * 60


class MonitorService:

    _instance = None
    _lock = threading.RLock()

    def __init__(self):
        self.is_running = False
        self.status = "Idle"
        self._thread = None
        self._stop = threading.Event()
        self._prefs = Prefs.shared()
        self._log = EventLog.shared()
        # Per-app throttle so persistently-unverifiable apps don't spam the alert.
        self._last_alert_at = {}
        # Tracks display sleep/lock transitions so the pause is logged once, not every tick.
        self._screen_was_visible = True
        # Consecutive foreground windows we were not permitted to identify.
        self._unreadable_streak = 0
        self._listeners = []

    @classmethod
    def shared(cls) -> "MonitorService":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def subscribe(self, fn):
        self._listeners.append(fn)

    def _set_status(self, text):
        self.status = text
        for fn in list(self._listeners):
            try:
                fn()
            except Exception:
                pass

    # ---- lifecycle ---------------------------------------------------------------------

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self.is_running = True
            self._prefs.monitoring_enabled = True
            self._log.add("[run] monitoring started" + (" [TEST]" if self._prefs.dry_run else ""))
            self._thread = threading.Thread(target=self._loop, name="guardian-monitor", daemon=True)
            self._thread.start()
        self._set_status("Monitoring active")

    def stop(self) -> None:
        with self._lock:
            self._stop.set()
            self._thread = None
            self.is_running = False
            self._prefs.monitoring_enabled = False
            self._log.add("[stop] monitoring stopped")
        self._set_status("Stopped")

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                active = self._tick()
            except Exception as e:
                # A crash in the loop is itself a bypass; log it and keep going.
                self._log.add(f"[warn] monitor tick failed: {e}")
                active = False
            self._stop.wait(MIN_GAP if active else IDLE_POLL)

    # ---- one check ---------------------------------------------------------------------

    def _tick(self) -> bool:
        """Returns True if a monitored app was on screen and was actually checked."""
        # A block overlay is up — the screen is already covered by us; don't capture/evaluate.
        if BlockController.shared().is_blocking:
            return False

        # Display asleep / locked / screen saver: nobody can be looking at anything, and capturing
        # would just hand us a black frame that reads as "can't see" and alerts. Pause instead.
        if not screen_state.is_visible():
            if self._screen_was_visible:
                self._screen_was_visible = False
                why = screen_state.reason()
                self._log.add(f"[zzz] screen {why} - monitoring paused")
                self._set_status(f"Screen {why}")
            return False
        if not self._screen_was_visible:
            self._screen_was_visible = True
            self._log.add("[eye] screen back on - monitoring resumed")
            self._set_status("Monitoring active")

        fg = foreground_app.identifier()

        # A foreground window whose process we're not allowed to query is a real Windows blind spot
        # (an elevated app while Guardian runs unelevated). It is never a hard block, but it is not
        # ignored either: after a few consecutive readings the contact is told.
        if fg == foreground_app.UNREADABLE:
            self._unreadable_streak += 1
            if self._unreadable_streak == 5:
                self._log.add("[blind] foreground app can't be identified (elevated process?)")
                if not self._prefs.dry_run and self._prefs.alert_on_unverifiable:
                    self._send_alert(
                        "unreadable-foreground",
                        "[Guardian] Can't identify the app in front",
                        "Guardian could not identify the app in the foreground on this PC "
                        "(it is running with higher privileges than Guardian). "
                        "Monitoring can't see what it is.", throttle=True)
            return False
        self._unreadable_streak = 0

        monitored = self._prefs.monitored_apps
        if not fg or fg not in monitored:
            return False

        # User dismissed a block for this app recently — leave it alone until the override expires.
        if overrides.is_active(fg):
            return False

        dry = self._prefs.dry_run
        name = foreground_app.short_name(fg)

        # Grab a screenshot of the monitor the app is on.
        cap_start = time.time()
        frame = screen_capturer.capture()
        cap_ms = int((time.time() - cap_start) * 1000)
        self._log.add(f"[cap] screenshot {name} ({cap_ms}ms capture)" + (" [TEST]" if dry else ""))
        self._set_status(f"Checking {name}...")

        # 1. Couldn't capture at all -> can't verify (safe handling).
        if frame is None:
            self._handle_unverifiable(fg, name, "screen could not be captured", dry)
            return True

        # 2. Captured but blank/uniform -> protected/blank -> can't verify.
        if frame_quality.is_unreadable(frame):
            self._handle_unverifiable(fg, name, "screen is blank or capture-protected", dry)
            return True

        # 3. Ask the AI.
        ai_start = time.time()
        client = OllamaClient(self._prefs)
        cfg = client.config()
        verdict = client.evaluate(frame, cfg)
        ai_ms = int((time.time() - ai_start) * 1000)

        if verdict.violation:
            if dry:
                self._log.add(f"[WOULD BLOCK] {name} ({ai_ms}ms) - {verdict.reason} [TEST]")
                self._set_status(f"WOULD block {name}")
            else:
                self._log.add(f"[BLOCK] {name} VIOLATION ({ai_ms}ms) - {verdict.reason}")
                self._enforce_violation(fg, name, verdict.reason)
            return True

        if verdict.transient:
            # Transient backend hiccup (HTTP 503/429/5xx, timeout): the AI is busy, NOT the user
            # hiding anything — so we NEVER hide/quit here. Log and move on; next tick retries.
            self._log.add(f"[busy] {name} AI busy - skipped ({ai_ms}ms) - {verdict.reason}")
            self._set_status(f"AI busy - skipped {name}")
            return True

        if verdict.undetermined:
            self._handle_unverifiable(fg, name, f"AI could not analyse ({verdict.reason})", dry)
            return True

        self._log.add(f"[ok] {name} cleared ({ai_ms}ms, {cfg.model})")
        self._set_status(f"Cleared {name}")
        return True

    # ---- enforcement -------------------------------------------------------------------

    def _enforce_violation(self, identifier: str, name: str, reason: str) -> None:
        """Confirmed guideline violation: raise the full-screen block overlay (dismiss/override with
        the passcode) + push alert."""
        self._prefs.last_violation_at = time.time()
        self._set_status(f"BLOCKED {name}")
        BlockController.shared().show(identifier, name, reason)
        notify_local(f"Guardian blocked {name}", reason)
        self._send_alert(identifier, f"[Guardian] Blocked {name}",
                         f"Guardian blocked the screen in {name}.\n\nReason: {reason}",
                         throttle=False)

    def _handle_unverifiable(self, identifier: str, name: str, why: str, dry: bool) -> None:
        """A monitored app's screen could NOT be verified (blank/protected frame, capture failure,
        or AI unreachable). Never closes anything unless the user opted in. Logs + pushes."""
        if dry:
            self._log.add(f"[blind] {name} CAN'T SEE - {why} - would alert [TEST]")
            self._set_status(f"Can't see {name}")
            return
        self._log.add(f"[blind] {name} CAN'T SEE - {why}")
        self._set_status(f"Can't see {name}")
        if self._prefs.alert_on_unverifiable:
            self._send_alert(identifier, f"[Guardian] Couldn't verify {name}",
                             f"Guardian could not see what was on screen in {name} ({why}).",
                             throttle=True)
        if self._prefs.close_unverifiable:
            foreground_app.hide(identifier)

    def _send_alert(self, key: str, title: str, body: str, throttle: bool) -> None:
        if throttle:
            last = self._last_alert_at.get(key)
            if last is not None and time.time() - last < ALERT_THROTTLE:
                return
            self._last_alert_at[key] = time.time()
        full_body = f"{body}\n\n{datetime.now()}"
        cfg = pusher.Config(self._prefs.push_enabled, self._prefs.ntfy_server,
                            self._prefs.ntfy_topic)
        err = pusher.send(cfg, title, full_body)
        if err:
            self._log.add(f"[warn] push failed: {err}")
