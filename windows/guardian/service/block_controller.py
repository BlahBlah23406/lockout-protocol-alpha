"""Port of `Service/BlockController.swift`.

Shows a FULL-SCREEN, always-on-top block overlay across every monitor when a violation is
confirmed. The offending app is covered until the user answers — with the passcode to *keep* using
it, or with a plain button that closes it. Dismissing grants a short override so it won't re-block
immediately.

macOS put the window at `.screenSaver` level and it stayed put. Windows has no window level above
everything, so the overlay re-asserts topmost on a short timer: a reflex Alt-Tab must not clear it,
which is the same "a violation costs a conscious tap" rule the Android `BlockGate` enforces.
"""

import threading
import tkinter as tk

from ..capture import foreground_app
from ..focus.session import SessionStore
from ..models import judgements
from ..ui import block_view, tkroot
from ..win32 import monitor_rects
from . import overrides

LIFT_INTERVAL_MS = 400


class BlockController:

    _instance = None
    _lock = threading.RLock()

    def __init__(self):
        self._windows = []
        self._current = None
        self._session = None
        self._judgement_id = ""
        self._lift_job = None

    @classmethod
    def shared(cls) -> "BlockController":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @property
    def is_blocking(self) -> bool:
        return self._current is not None

    @property
    def current(self):
        return self._current

    def show(self, identifier: str, app_name: str, reason: str,
             session=None, judgement_id: str = "") -> None:
        """Raise the overlay. `session` decides which accountability level the block is shown at;
        `judgement_id` ties a later "false alarm" press back to the exact check that caused it."""
        with self._lock:
            if self._current is not None:
                return                      # one block at a time
            self._current = (identifier, app_name, reason)
            self._session = session
            self._judgement_id = judgement_id
        tkroot.run_on_ui(lambda: self._build(identifier, app_name, reason, session))

    # ---- UI thread ---------------------------------------------------------------------

    def _build(self, identifier, app_name, reason, session=None):
        root = tkroot.get_root()
        if root is None:
            return
        for i, (left, top, right, bottom) in enumerate(monitor_rects()):
            w = tk.Toplevel(root)
            w.overrideredirect(True)
            w.configure(bg="#05070D")
            w.geometry(f"{right - left}x{bottom - top}+{left}+{top}")
            w.attributes("-topmost", True)
            block_view.build(w, app_name, reason,
                             on_override=self.finish_override,
                             on_quit=self.finish_quit,
                             focus=(i == 0),
                             session=session,
                             on_false_alarm=self.mark_false_alarm)
            self._windows.append(w)
        self._keep_on_top()

    def _keep_on_top(self):
        """Re-assert topmost so the blocked app can't simply be raised over the overlay."""
        if not self._windows:
            return
        for w in list(self._windows):
            try:
                w.attributes("-topmost", True)
                w.lift()
            except tk.TclError:
                pass
        root = tkroot.get_root()
        if root is not None:
            self._lift_job = root.after(LIFT_INTERVAL_MS, self._keep_on_top)

    # ---- exits -------------------------------------------------------------------------

    def finish_override(self) -> None:
        """"Override" — keep using the app. Grants a 5-minute reprieve and tears down the overlay.
        In a locked session the passcode was already checked in `block_view`.

        The override also pauses the *session* briefly, not just this app. Being re-challenged 90
        seconds after you deliberately said "yes, I need this" is how a monitor teaches people to
        ignore it, and an override the user paid for with a passcode should buy a little peace."""
        cur = self._current
        session = self._session
        if cur:
            overrides.grant(cur[0])
        if session is not None:
            store = SessionStore.shared()
            store.record_override()
            store.pause(min(300, max(session.interval_seconds * 2, 120)))
            if session.alerts_partner():
                self._alert_override(cur, session)
        self._teardown()

    def mark_false_alarm(self) -> None:
        """Experimental: record that this block was wrong, for the learner to pick up later."""
        if self._judgement_id:
            judgements.add_feedback(self._judgement_id, judgements.FB_FALSE_ALARM)

    def _alert_override(self, cur, session) -> None:
        """A locked session that gets overridden is exactly the event a partner signed up to hear
        about — the block itself is only half the story."""
        from ..models.prefs import Prefs
        from ..push import pusher
        prefs = Prefs.shared()
        name = cur[1] if cur else "an app"
        cfg = pusher.Config(prefs.push_enabled, prefs.ntfy_server, prefs.ntfy_topic)
        pusher.send(cfg, f"[Lockout] Override used in {name}",
                    f"Task: {session.task}\n\nThe block on {name} was overridden with the "
                    f"passcode. That is override #{session.override_count} this session.")

    def finish_quit(self) -> None:
        """"Dismiss" — the no-code, compliant exit: close the offending app, then tear down.
        A short override covers the moment between asking it to close and it actually closing."""
        cur = self._current
        self._teardown()
        if cur:
            identifier = cur[0]
            overrides.grant(identifier, seconds=30)
            threading.Thread(target=foreground_app.quit, args=(identifier,),
                             name="guardian-close-app", daemon=True).start()

    def _teardown(self) -> None:
        root = tkroot.get_root()
        if root is not None and self._lift_job is not None:
            try:
                root.after_cancel(self._lift_job)
            except Exception:
                pass
        self._lift_job = None
        for w in self._windows:
            try:
                w.destroy()
            except tk.TclError:
                pass
        self._windows = []
        with self._lock:
            self._current = None
            self._session = None
            self._judgement_id = ""
