"""A focus session: one declared task, for a stretch of time, on a chosen set of apps.

This is the unit the whole app is now organised around. Before, monitoring was a mode you left
running forever. Now it is a *session* you deliberately start — "working on math test prep",
90 minutes — and when it ends, nothing is watched at all. That is a deliberate product decision
and not just a UI change: a tool that only ever looks at your screen during a window you opened
yourself is far easier to trust, and far easier to keep installed, than one that is always on.

Two accountability levels, and the difference between them is who holds the exit:

    "self"    You can end the session or dismiss a block yourself, no passcode. The block still
              interrupts you and still goes in the log — the friction *is* the product — but you
              are the only one holding you to it. This is the honest default for most people.
    "locked"  Ending the session early, or overriding a block, needs the passcode. Blocks and
              overrides both fire an ntfy alert to your accountability partner's private link.
              For when "I'll just check one thing" has already won too many times.

The session is persisted to disk after every mutation. If Guardian is killed and relaunched
mid-session it picks the session back up — otherwise force-quitting the app would be a one-click
bypass, which would make "locked" meaningless.
"""

import json
import os
import random
import string
import threading
import time

from ..paths import data_dir

SESSION_FILE = data_dir() / "focus_session.json"
HISTORY_FILE = data_dir() / "focus_history.jsonl"

ACC_SELF = "self"
ACC_LOCKED = "locked"
ACCOUNTABILITY_LEVELS = (ACC_SELF, ACC_LOCKED)

# How often we check, in seconds. The default is a compromise found by using it: much below a
# minute and you are paying for inference constantly and being interrupted by transients; much
# above five and a genuine detour has already eaten the block it should have prevented.
DEFAULT_INTERVAL = 120
MIN_INTERVAL = 15
MAX_INTERVAL = 3600

ACCOUNTABILITY_LABELS = {
    ACC_SELF: "Self-managed — you can override your own blocks",
    ACC_LOCKED: "Locked — passcode to override, partner is alerted",
}


def _new_id() -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "fs_" + "".join(random.choice(alphabet) for _ in range(10))


def clamp_interval(seconds) -> int:
    try:
        v = int(seconds)
    except (TypeError, ValueError):
        return DEFAULT_INTERVAL
    return min(max(v, MIN_INTERVAL), MAX_INTERVAL)


class FocusSession:
    """One declared stretch of work. Plain data; the store owns persistence."""

    __slots__ = ("id", "task", "started_at", "planned_minutes", "interval_seconds",
                 "accountability", "extra_apps", "allowed_apps", "provider_id",
                 "ended_at", "ended_reason", "checks", "off_task_count", "override_count",
                 "paused_until")

    def __init__(self, task, planned_minutes=0, interval_seconds=DEFAULT_INTERVAL,
                 accountability=ACC_SELF, extra_apps=None, allowed_apps=None,
                 provider_id="", session_id=None, started_at=None):
        self.id = session_id or _new_id()
        self.task = (task or "").strip()
        self.started_at = float(started_at if started_at is not None else time.time())
        # 0 means open-ended: run until I say stop. Useful, and the only sane option for the
        # "locked" level to *not* offer, since an open-ended locked session with a lost passcode
        # is exactly the lockout we promise never to create (see `SAFEGUARDS.md`).
        self.planned_minutes = max(int(planned_minutes or 0), 0)
        self.interval_seconds = clamp_interval(interval_seconds)
        self.accountability = accountability if accountability in ACCOUNTABILITY_LEVELS else ACC_SELF
        # One-off, this-session-only adjustments on top of the saved default watchlist.
        self.extra_apps = set(extra_apps or ())
        self.allowed_apps = set(allowed_apps or ())
        self.provider_id = provider_id or ""
        self.ended_at = None
        self.ended_reason = ""
        self.checks = 0
        self.off_task_count = 0
        self.override_count = 0
        self.paused_until = 0.0

    # ---- watchlist ---------------------------------------------------------------------

    def watchlist(self, default_apps) -> set:
        """The apps actually watched this session: your saved defaults, plus anything you added
        just for today, minus anything you excused just for today.

        The exclusion is not a loophole — it is what makes the default list usable. If Slack is
        normally a distraction but today's task *is* answering Slack, you shouldn't have to edit
        your permanent settings (and then forget to put them back)."""
        return (set(default_apps) | self.extra_apps) - self.allowed_apps

    # ---- lifecycle ---------------------------------------------------------------------

    @property
    def is_active(self) -> bool:
        return self.ended_at is None

    @property
    def elapsed_seconds(self) -> float:
        return max(time.time() - self.started_at, 0.0)

    @property
    def remaining_seconds(self):
        """Seconds left, or None for an open-ended session."""
        if not self.planned_minutes:
            return None
        return max(self.planned_minutes * 60 - self.elapsed_seconds, 0.0)

    @property
    def is_over(self) -> bool:
        r = self.remaining_seconds
        return r is not None and r <= 0

    @property
    def is_paused(self) -> bool:
        return self.paused_until > time.time()

    def requires_passcode_to_end(self) -> bool:
        """Only "locked" sessions hold their own exit. A "self" session ends when you say so —
        pretending otherwise would be a lie, since you can always quit the app."""
        return self.accountability == ACC_LOCKED

    def alerts_partner(self) -> bool:
        return self.accountability == ACC_LOCKED

    # ---- serialisation -----------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "task": self.task,
            "started_at": self.started_at,
            "planned_minutes": self.planned_minutes,
            "interval_seconds": self.interval_seconds,
            "accountability": self.accountability,
            "extra_apps": sorted(self.extra_apps),
            "allowed_apps": sorted(self.allowed_apps),
            "provider_id": self.provider_id,
            "ended_at": self.ended_at,
            "ended_reason": self.ended_reason,
            "checks": self.checks,
            "off_task_count": self.off_task_count,
            "override_count": self.override_count,
            "paused_until": self.paused_until,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "FocusSession":
        s = cls(task=d.get("task", ""),
                planned_minutes=d.get("planned_minutes", 0),
                interval_seconds=d.get("interval_seconds", DEFAULT_INTERVAL),
                accountability=d.get("accountability", ACC_SELF),
                extra_apps=d.get("extra_apps"),
                allowed_apps=d.get("allowed_apps"),
                provider_id=d.get("provider_id", ""),
                session_id=d.get("id"),
                started_at=d.get("started_at"))
        s.ended_at = d.get("ended_at")
        s.ended_reason = d.get("ended_reason", "")
        s.checks = int(d.get("checks", 0) or 0)
        s.off_task_count = int(d.get("off_task_count", 0) or 0)
        s.override_count = int(d.get("override_count", 0) or 0)
        s.paused_until = float(d.get("paused_until", 0) or 0)
        return s

    def summary_line(self) -> str:
        mins = int(self.elapsed_seconds // 60)
        return (f"{self.task or '(no task)'} - {mins}m, {self.checks} checks, "
                f"{self.off_task_count} off-task, {self.override_count} override(s)")


class SessionStore:
    """The one active session, on disk, plus an append-only history of finished ones."""

    _instance = None
    _lock = threading.RLock()

    def __init__(self):
        self._current = None
        self._listeners = []
        self._load()

    @classmethod
    def shared(cls) -> "SessionStore":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    # ---- change notification -----------------------------------------------------------

    def subscribe(self, fn):
        self._listeners.append(fn)

    def _notify(self):
        for fn in list(self._listeners):
            try:
                fn()
            except Exception:
                pass

    # ---- persistence -------------------------------------------------------------------

    def _load(self):
        try:
            d = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
            s = FocusSession.from_dict(d)
            self._current = s if s.is_active else None
        except Exception:
            self._current = None

    def _save(self):
        try:
            if self._current is None:
                if SESSION_FILE.exists():
                    os.remove(SESSION_FILE)
                return
            tmp = SESSION_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._current.to_dict(), indent=2), encoding="utf-8")
            tmp.replace(SESSION_FILE)
        except Exception:
            pass

    def _archive(self, session: FocusSession):
        try:
            with open(HISTORY_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(session.to_dict()) + "\n")
        except Exception:
            pass

    # ---- accessors ---------------------------------------------------------------------

    @property
    def current(self):
        """The live session, or None. Expiry is evaluated lazily on read so nothing depends on a
        timer having fired — a laptop that was asleep past the end time still ends cleanly."""
        with self._lock:
            s = self._current
            if s is not None and s.is_over:
                self.end("time's up")
                return None
            return self._current

    @property
    def is_active(self) -> bool:
        return self.current is not None

    # ---- mutations ---------------------------------------------------------------------

    def start(self, session: FocusSession) -> FocusSession:
        with self._lock:
            if self._current is not None:
                self.end("replaced by a new session")
            self._current = session
            self._save()
        self._notify()
        return session

    def end(self, reason: str = "ended") -> None:
        with self._lock:
            s = self._current
            if s is None:
                return
            s.ended_at = time.time()
            s.ended_reason = reason
            self._archive(s)
            self._current = None
            self._save()
        self._notify()

    def pause(self, seconds: float) -> None:
        """Used by the block screen's override: stop checking for a bit so the user isn't
        re-blocked mid-sentence while they finish what they said they needed to do."""
        with self._lock:
            if self._current is None:
                return
            self._current.paused_until = time.time() + max(seconds, 0)
            self._save()
        self._notify()

    def record_check(self, off_task: bool = False) -> None:
        with self._lock:
            if self._current is None:
                return
            self._current.checks += 1
            if off_task:
                self._current.off_task_count += 1
            self._save()

    def record_override(self) -> None:
        with self._lock:
            if self._current is None:
                return
            self._current.override_count += 1
            self._save()
        self._notify()

    def add_session_app(self, identifier: str) -> None:
        """Add a one-off app to the live session (from the block screen or the mini panel)."""
        with self._lock:
            if self._current is None:
                return
            self._current.extra_apps.add(identifier)
            self._current.allowed_apps.discard(identifier)
            self._save()
        self._notify()

    def allow_session_app(self, identifier: str) -> None:
        """Excuse an app for the rest of this session only."""
        with self._lock:
            if self._current is None:
                return
            self._current.allowed_apps.add(identifier)
            self._current.extra_apps.discard(identifier)
            self._save()
        self._notify()

    def history(self, limit: int = 50) -> list:
        try:
            lines = HISTORY_FILE.read_text(encoding="utf-8").splitlines()
        except Exception:
            return []
        out = []
        for line in lines[-limit:]:
            try:
                out.append(FocusSession.from_dict(json.loads(line)))
            except Exception:
                continue          # a truncated last line after a hard kill is expected, not fatal
        return out
