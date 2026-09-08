"""The monitoring loop.

Guardian has two modes and this is where they meet:

**Focus mode** (the product). A session is running — the user declared a task like "working on
math test prep" — so every `interval_seconds` we screenshot whichever watched app is in front and
ask the model whether that screen belongs to that task. Off-task screens get blocked at whatever
accountability level the session was started with.

**Content rules** (opt-in, off by default). The original behaviour: an always-on classifier
checking screens against written content guidelines. Kept because it works and people use it, but
it is no longer what the app is for.

The single most important structural change from the old version: **when no session is running,
nothing is captured at all.** Not "captured and discarded" — the screenshot is never taken. A
monitor that only looks during a window you opened yourself is a fundamentally different thing to
live with than one that is always watching, and that difference is worth the extra branch here.

Cadence is driven by the session's interval rather than by how fast the model answers. The old
loop fired again 1.2s after each reply, which is right for content safety (a single frame of the
wrong thing matters) and completely wrong here: it would burn hundreds of inference calls an hour
to answer a question whose answer changes over minutes.
"""

import threading
import time
from datetime import datetime

from ..ai import frame_quality, providers
from ..ai.ollama_client import OllamaClient
from ..capture import foreground_app, screen_capturer, screen_state
from ..focus.session import SessionStore
from ..models import judgements
from ..models.event_log import EventLog
from ..models.prefs import Prefs
from ..notify import notify_local
from ..push import pusher
from . import overrides
from .block_controller import BlockController

# Content-rules cadence (unchanged from the original app).
MIN_GAP = 1.2
IDLE_POLL = 2.5

# Focus-mode cadence. `FOCUS_IDLE_POLL` is how often we re-check *which app is in front* while
# not on a watched app — cheap (a Win32 call, no capture, no inference), so it can be brisk.
FOCUS_IDLE_POLL = 3.0
# After a transient backend failure, retry sooner than the full interval but not instantly.
TRANSIENT_RETRY = 20.0

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
        self._sessions = SessionStore.shared()
        # Per-app throttle so persistently-unverifiable apps don't spam the alert.
        self._last_alert_at = {}
        self._screen_was_visible = True
        self._unreadable_streak = 0
        # When the next focus check is due, per app. Keyed by app so switching apps checks the new
        # one promptly instead of inheriting the previous app's countdown — the moment you switch
        # into a distraction is exactly the moment worth looking.
        self._next_check_at = {}
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
            self._next_check_at.clear()
            mode = "focus" if self._sessions.is_active else "content-rules"
            self._log.add(f"[run] monitoring started ({mode})"
                          + (" [TEST]" if self._prefs.dry_run else ""))
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
                wait = self._tick()
            except Exception as e:
                # A crash in the loop is itself a bypass; log it and keep going.
                self._log.add(f"[warn] monitor tick failed: {e}")
                wait = IDLE_POLL
            self._stop.wait(max(float(wait), 0.5))

    # ---- one tick ----------------------------------------------------------------------

    def _tick(self) -> float:
        """Do at most one unit of work. Returns how many seconds to wait before the next tick."""
        # A block overlay is up — we are already covering the screen; don't capture or evaluate.
        if BlockController.shared().is_blocking:
            return IDLE_POLL

        # Display asleep / locked / screen saver: nobody is looking at anything, and capturing
        # would hand us a black frame that reads as "can't see" and alerts. Pause instead.
        if not screen_state.is_visible():
            if self._screen_was_visible:
                self._screen_was_visible = False
                why = screen_state.reason()
                self._log.add(f"[zzz] screen {why} - monitoring paused")
                self._set_status(f"Screen {why}")
            return IDLE_POLL
        if not self._screen_was_visible:
            self._screen_was_visible = True
            self._log.add("[eye] screen back on - monitoring resumed")
            self._set_status("Monitoring active")

        session = self._sessions.current
        if session is not None:
            return self._focus_tick(session)
        if self._prefs.content_rules_enabled:
            return MIN_GAP if self._content_tick() else IDLE_POLL

        # Nothing to do: no session, content rules off. Explicitly *not* capturing anything.
        self._set_status("No focus session - not watching")
        return IDLE_POLL

    # ---- focus mode --------------------------------------------------------------------

    def _focus_tick(self, session) -> float:
        interval = float(session.interval_seconds)

        if session.is_paused:
            left = max(session.paused_until - time.time(), 0)
            self._set_status(f"Paused {int(left)}s")
            return min(left + 0.5, interval)

        fg = foreground_app.identifier()

        if fg == foreground_app.UNREADABLE:
            self._unreadable_streak += 1
            if self._unreadable_streak == 5:
                self._log.add("[blind] foreground app can't be identified (elevated process?)")
                if not self._prefs.dry_run and self._prefs.alert_on_unverifiable:
                    self._send_alert(
                        "unreadable-foreground", "[Lockout] Can't identify the app in front",
                        "Guardian could not identify the app in the foreground on this PC "
                        "(it is running with higher privileges than Guardian).", throttle=True)
            return FOCUS_IDLE_POLL
        self._unreadable_streak = 0

        watchlist = session.watchlist(self._prefs.monitored_apps)
        if not fg or fg not in watchlist:
            # Not a watched app. In focus mode this is the normal, uninteresting case — you are in
            # your editor, or your terminal, or anything you never asked to be policed.
            self._set_status(self._idle_status(session))
            return FOCUS_IDLE_POLL

        if overrides.is_active(fg):
            return FOCUS_IDLE_POLL

        # Rate-limit per app so switching back and forth can't be used to force a check storm.
        due_at = self._next_check_at.get(fg, 0)
        now = time.time()
        if now < due_at:
            self._set_status(self._idle_status(session))
            return min(due_at - now, FOCUS_IDLE_POLL)

        name = foreground_app.short_name(fg)
        title = foreground_app.title()
        dry = self._prefs.dry_run

        frame = screen_capturer.capture()
        if frame is None:
            self._handle_unverifiable(fg, name, "screen could not be captured", dry)
            self._next_check_at[fg] = time.time() + interval
            return interval
        if frame_quality.is_unreadable(frame):
            self._handle_unverifiable(fg, name, "screen is blank or capture-protected", dry)
            self._next_check_at[fg] = time.time() + interval
            return interval

        self._set_status(f"Checking {name}...")
        cfg = self._prefs.provider_config()
        started = time.time()
        verdict = providers.evaluate(
            cfg, frame, session.task, name, title,
            extra_notes=self._extra_notes(session, fg),
            on_key_worked=self._prefs.promote_api_key)
        ms = int((time.time() - started) * 1000)

        # Transient backend trouble is never evidence about the user: log, retry sooner, no block.
        if verdict.transient:
            self._log.add(f"[busy] {name} - AI unavailable ({verdict.reason}) - skipped")
            self._set_status("AI unavailable - retrying")
            self._next_check_at[fg] = time.time() + TRANSIENT_RETRY
            return TRANSIENT_RETRY

        self._next_check_at[fg] = time.time() + interval

        if verdict.undetermined:
            self._handle_unverifiable(fg, name, f"AI could not analyse ({verdict.reason})", dry)
            return interval

        if verdict.on_task:
            self._sessions.record_check(off_task=False)
            judgements.record(session, fg, name, title, "on_task", verdict.reason,
                              verdict.confidence, "allowed", cfg.describe())
            self._log.add(f"[ok] {name} on task ({ms}ms, {cfg.model})")
            self._set_status(self._idle_status(session))
            return interval

        # Off task.
        self._sessions.record_check(off_task=True)
        action = "logged" if dry else "blocked"
        jid = judgements.record(session, fg, name, title, "off_task", verdict.reason,
                                verdict.confidence, action, cfg.describe())
        if dry:
            self._log.add(f"[WOULD BLOCK] {name} off task ({ms}ms) - {verdict.reason} [TEST]")
            self._set_status(f"WOULD block {name}")
        else:
            self._log.add(f"[BLOCK] {name} OFF TASK ({ms}ms) - {verdict.reason}")
            self._enforce_off_task(session, fg, name, verdict, jid)
        return interval

    def _idle_status(self, session) -> str:
        left = session.remaining_seconds
        if left is None:
            return f"Focus: {session.task[:40]}"
        return f"Focus: {session.task[:32]} ({int(left // 60)}m left)"

    def _extra_notes(self, session, app_id: str) -> str:
        """Standing notes handed to the classifier: the user's own, plus anything the experimental
        learner has concluded. Both are capped hard — a prompt suffix that grows without bound
        eventually costs more than the screenshot does."""
        notes = [self._prefs.focus_notes.strip()]
        if self._prefs.learning_enabled:
            try:
                from ..focus import learned
                notes.append(learned.prompt_suffix(session.task, app_id))
            except Exception:
                pass                    # the learner is experimental; it must never break a check
        return "\n".join(n for n in notes if n)[:1500]

    def _enforce_off_task(self, session, identifier: str, name: str, verdict, jid: str) -> None:
        """Raise the block. What the block *offers* depends on the accountability level the user
        chose when they started the session — that choice is the whole point of the two levels,
        so it is read from the session and not from a global setting that could have drifted."""
        self._prefs.last_violation_at = time.time()
        self._set_status(f"BLOCKED {name}")
        BlockController.shared().show(identifier, name, verdict.reason,
                                      session=session, judgement_id=jid)
        notify_local(f"Off task in {name}", verdict.reason or session.task)

        if session.alerts_partner():
            self._send_alert(
                identifier, f"[Lockout] Off task in {name}",
                f"Task: {session.task}\n\n{name} was blocked.\nReason: {verdict.reason}",
                throttle=False)

    # ---- content-rules mode (opt-in; the original behaviour) ---------------------------

    def _content_tick(self) -> bool:
        """Returns True if a monitored app was on screen and was actually checked."""
        fg = foreground_app.identifier()
        if fg == foreground_app.UNREADABLE:
            self._unreadable_streak += 1
            if self._unreadable_streak == 5:
                self._log.add("[blind] foreground app can't be identified (elevated process?)")
            return False
        self._unreadable_streak = 0

        if not fg or fg not in self._prefs.monitored_apps:
            return False
        if overrides.is_active(fg):
            return False

        dry = self._prefs.dry_run
        name = foreground_app.short_name(fg)
        frame = screen_capturer.capture()
        if frame is None:
            self._handle_unverifiable(fg, name, "screen could not be captured", dry)
            return True
        if frame_quality.is_unreadable(frame):
            self._handle_unverifiable(fg, name, "screen is blank or capture-protected", dry)
            return True

        client = OllamaClient(self._prefs)
        cfg = client.config()
        started = time.time()
        verdict = client.evaluate(frame, cfg)
        ms = int((time.time() - started) * 1000)

        if verdict.violation:
            if dry:
                self._log.add(f"[WOULD BLOCK] {name} ({ms}ms) - {verdict.reason} [TEST]")
            else:
                self._log.add(f"[BLOCK] {name} VIOLATION ({ms}ms) - {verdict.reason}")
                self._prefs.last_violation_at = time.time()
                BlockController.shared().show(identifier=fg, app_name=name, reason=verdict.reason)
                notify_local(f"Guardian blocked {name}", verdict.reason)
                self._send_alert(fg, f"[Lockout] Blocked {name}",
                                 f"Content rule triggered in {name}.\n\nReason: {verdict.reason}",
                                 throttle=False)
            return True
        if verdict.transient:
            self._log.add(f"[busy] {name} AI busy - skipped ({ms}ms) - {verdict.reason}")
            return True
        if verdict.undetermined:
            self._handle_unverifiable(fg, name, f"AI could not analyse ({verdict.reason})", dry)
            return True

        self._log.add(f"[ok] {name} cleared ({ms}ms, {cfg.model})")
        return True

    # ---- shared -------------------------------------------------------------------------

    def _handle_unverifiable(self, identifier: str, name: str, why: str, dry: bool) -> None:
        """A watched app's screen could NOT be read (blank/protected frame, capture failure, or an
        answer we couldn't parse). Never blocks. This is the anti-lockout rule: a screen we cannot
        see is not a screen we get to punish."""
        if dry:
            self._log.add(f"[blind] {name} CAN'T SEE - {why} - would alert [TEST]")
            self._set_status(f"Can't see {name}")
            return
        self._log.add(f"[blind] {name} CAN'T SEE - {why}")
        self._set_status(f"Can't see {name}")
        session = self._sessions.current
        alerts = self._prefs.alert_on_unverifiable and (session is None or session.alerts_partner())
        if alerts:
            self._send_alert(identifier, f"[Lockout] Couldn't verify {name}",
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
        full_body = f"{body}\n\n{datetime.now():%Y-%m-%d %H:%M:%S}"
        cfg = pusher.Config(self._prefs.push_enabled, self._prefs.ntfy_server,
                            self._prefs.ntfy_topic)
        err = pusher.send(cfg, title, full_body)
        if err:
            self._log.add(f"[warn] push failed: {err}")
