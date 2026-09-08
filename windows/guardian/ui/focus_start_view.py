"""The "what are you working on?" window — the front door of the whole app.

Everything about this screen is trying to get the user to typing and pressing START in under ten
seconds, because a focus tool that takes two minutes to arm gets used on the days you least need
it and skipped on the days you do. So: the task box is prefilled with last time's answer and
focused on open, every other field has a working default carried over from settings, and the
per-session app tweaks are one line of summary text behind one button.

The one place we deliberately add friction is the accountability picker. Choosing "locked" means
handing your own passcode over to future-you-who-wants-to-stop, so the consequences are spelled
out next to the option rather than hidden in a docs page.
"""

import tkinter as tk

from . import theme as T
from .app_picker_view import AppPickerWindow
from ..focus.session import (ACC_LOCKED, ACC_SELF, DEFAULT_INTERVAL, FocusSession, SessionStore,
                             clamp_interval)
from ..models.prefs import Prefs

# Offered interval presets, in seconds. Anything else is typed into the box.
INTERVAL_CHOICES = [(30, "30 sec"), (60, "1 min"), (120, "2 min"), (300, "5 min"), (600, "10 min")]
DURATION_CHOICES = [(25, "25 min"), (50, "50 min"), (90, "90 min"), (0, "open-ended")]


class FocusStartWindow(tk.Toplevel):

    def __init__(self, master, on_started=None):
        super().__init__(master)
        self.prefs = Prefs.shared()
        self.store = SessionStore.shared()
        self.on_started = on_started

        self.title("Start a focus session")
        self.configure(bg=T.SPACE)
        self.geometry("620x640")
        self.minsize(560, 560)
        self.attributes("-topmost", True)
        T.apply_ttk_dark(self)

        self.interval = tk.IntVar(value=self.prefs.focus_interval)
        self.minutes = tk.IntVar(value=self.prefs.focus_minutes)
        self.accountability = tk.StringVar(value=self.prefs.focus_accountability)
        self._extra_apps = set()
        self._allowed_apps = set()

        self._build()

    # ---- layout ------------------------------------------------------------------------

    def _build(self):
        T.LcarsHeader(self, "Focus Session", "What are you working on?").pack(
            fill="x", padx=16, pady=(14, 12))

        body = tk.Frame(self, bg=T.SPACE)
        body.pack(fill="both", expand=True, padx=16)

        # --- the task itself ---
        tk.Label(body, text="I AM WORKING ON", bg=T.SPACE, fg=T.GOLD,
                 font=("Segoe UI Black", 9)).pack(anchor="w")
        tk.Label(body, text="Plain English. The model reads this exactly as you write it — "
                            "\"revising integration by parts for Friday's calc test\" works far "
                            "better than \"study\".",
                 bg=T.SPACE, fg=T.LILAC, font=("Segoe UI", 8), wraplength=560,
                 justify="left").pack(anchor="w", pady=(1, 5))

        self.task_box = tk.Text(body, height=3, bg=T.PANEL, fg=T.READOUT, insertbackground=T.READOUT,
                                relief="flat", bd=0, highlightthickness=1,
                                highlightbackground=T.BLUE, font=("Consolas", 11), wrap="word")
        self.task_box.pack(fill="x", pady=(0, 12))
        self.task_box.insert("1.0", self.prefs.last_task)
        self.task_box.after(120, lambda: (self.task_box.focus_force(),
                                          self.task_box.tag_add("sel", "1.0", "end-1c")))

        # --- duration + interval ---
        row = tk.Frame(body, bg=T.SPACE)
        row.pack(fill="x", pady=(0, 12))

        self._radio_group(row, "FOR", DURATION_CHOICES, self.minutes).pack(
            side="left", fill="x", expand=True, padx=(0, 8))
        self._radio_group(row, "CHECK EVERY", INTERVAL_CHOICES, self.interval).pack(
            side="left", fill="x", expand=True)

        tk.Label(body, text="Each check is one screenshot and one model call, so the interval is "
                            "also your cost dial. Local models are free — check as often as you like.",
                 bg=T.SPACE, fg=T.LILAC, font=("Segoe UI", 8), wraplength=560,
                 justify="left").pack(anchor="w", pady=(0, 12))

        # --- accountability ---
        tk.Label(body, text="ACCOUNTABILITY", bg=T.SPACE, fg=T.GOLD,
                 font=("Segoe UI Black", 9)).pack(anchor="w")
        acc_box = T.ReadoutPanel(body)
        acc_box.pack(fill="x", pady=(4, 12))

        self._accountability_option(
            acc_box, ACC_SELF, "Self-managed",
            "It blocks you and logs it — but you can wave it away yourself. No passcode, "
            "nobody is told. Start here.")
        self._accountability_option(
            acc_box, ACC_LOCKED, "Locked",
            "Overriding a block needs the passcode, and every block and override is pushed to "
            "your accountability partner's private ntfy link. Closing the app still always works.")

        self.acc_warning = tk.Label(body, text="", bg=T.SPACE, fg=T.GOLD, font=("Segoe UI", 8),
                                    wraplength=560, justify="left")
        self.acc_warning.pack(anchor="w", pady=(0, 8))
        self.accountability.trace_add("write", lambda *_: self._refresh_warning())

        # --- per-session apps ---
        tk.Label(body, text="APPS", bg=T.SPACE, fg=T.GOLD,
                 font=("Segoe UI Black", 9)).pack(anchor="w")
        self.apps_summary = tk.Label(body, text="", bg=T.SPACE, fg=T.READOUT,
                                     font=("Consolas", 9), anchor="w", justify="left",
                                     wraplength=560)
        self.apps_summary.pack(anchor="w", pady=(2, 4))
        tk.Button(body, text="Change apps for this session only…", command=self._edit_apps,
                  bg=T.SPACE, fg=T.BLUE, relief="flat", bd=0, cursor="hand2", anchor="w",
                  font=("Segoe UI Semibold", 9), activebackground=T.SPACE,
                  activeforeground=T.BLUE).pack(anchor="w", pady=(0, 8))

        # --- go ---
        footer = tk.Frame(self, bg=T.SPACE)
        footer.pack(fill="x", padx=16, pady=(6, 14))
        self.error = tk.Label(footer, text="", bg=T.SPACE, fg=T.RED, font=("Segoe UI", 9))
        self.error.pack(anchor="w", pady=(0, 6))
        T.LcarsButton(footer, "Start focus session", self._start, color=T.ORANGE).pack(
            side="left", fill="x", expand=True, padx=(0, 4))
        T.LcarsButton(footer, "Cancel", self.destroy, color=T.LILAC).pack(side="left", padx=(4, 0))

        self._refresh_warning()
        self._refresh_apps_summary()

    def _radio_group(self, parent, title, choices, var):
        box = tk.Frame(parent, bg=T.SPACE)
        tk.Label(box, text=title, bg=T.SPACE, fg=T.GOLD,
                 font=("Segoe UI Black", 9)).pack(anchor="w")
        inner = T.ReadoutPanel(box)
        inner.pack(fill="x", pady=(4, 0))
        for value, label in choices:
            tk.Radiobutton(inner, text=label, value=value, variable=var,
                           bg=T.PANEL, fg=T.READOUT, selectcolor=T.SPACE,
                           activebackground=T.PANEL, activeforeground=T.GOLD,
                           font=("Consolas", 9), anchor="w", bd=0,
                           highlightthickness=0).pack(fill="x", anchor="w")
        return box

    def _accountability_option(self, parent, value, label, blurb):
        tk.Radiobutton(parent, text=label, value=value, variable=self.accountability,
                       bg=T.PANEL, fg=T.GOLD, selectcolor=T.SPACE, activebackground=T.PANEL,
                       activeforeground=T.GOLD, font=("Segoe UI Semibold", 10), anchor="w",
                       bd=0, highlightthickness=0).pack(fill="x", anchor="w", pady=(4, 0))
        tk.Label(parent, text=blurb, bg=T.PANEL, fg=T.READOUT, font=("Segoe UI", 8),
                 wraplength=520, justify="left").pack(anchor="w", padx=(22, 6), pady=(0, 4))

    def _refresh_warning(self):
        """Say the awkward part out loud before they commit, not after."""
        if self.accountability.get() != ACC_LOCKED:
            self.acc_warning.configure(text="")
            return
        problems = []
        if not self.prefs.pin_set:
            problems.append("no passcode is set yet — set one in Settings first, or overrides "
                            "will need no code at all")
        if not self.prefs.push_enabled:
            problems.append("alerts are switched off, so nobody will actually be told")
        self.acc_warning.configure(
            text=("⚠  " + "; ".join(problems)) if problems
            else f"⚠  Alerts go to your private link: {self.prefs.ntfy_topic}")

    # ---- per-session apps --------------------------------------------------------------

    def _current_selection(self) -> set:
        return (self.prefs.monitored_apps | self._extra_apps) - self._allowed_apps

    def _edit_apps(self):
        AppPickerWindow(
            self, selection=self._current_selection(), on_done=self._on_apps,
            title="Apps for this session", subtitle="Just for today",
            note="Ticking an extra app watches it for this session only. Unticking one of your "
                 "defaults excuses it for this session only. Neither edits your saved watchlist.")

    def _on_apps(self, selected: set):
        """Store the *delta* against the saved defaults, not a copy of the list. If you later edit
        your default watchlist mid-session, a session started before that edit still tracks it —
        which is what people expect, and what a snapshot would silently get wrong."""
        default = self.prefs.monitored_apps
        self._extra_apps = set(selected) - default
        self._allowed_apps = default - set(selected)
        self._refresh_apps_summary()

    def _refresh_apps_summary(self):
        n = len(self._current_selection())
        bits = [f"{n} app(s) watched this session"]
        if self._extra_apps:
            bits.append(f"+{len(self._extra_apps)} added today")
        if self._allowed_apps:
            bits.append(f"-{len(self._allowed_apps)} excused today")
        self.apps_summary.configure(text="  ·  ".join(bits))

    # ---- start -------------------------------------------------------------------------

    def start_now(self):
        """Start immediately with whatever is prefilled — the "same again" path from the mini
        panel. Goes through exactly the same validation as the button, so a one-click restart
        cannot skip the checks (an open-ended locked session, an empty watchlist)."""
        self._start()

    def _start(self):
        task = self.task_box.get("1.0", "end").strip()
        if len(task) < 3:
            self.error.configure(text="Tell it what you're working on first.")
            return

        acc = self.accountability.get()
        minutes = int(self.minutes.get() or 0)
        if acc == ACC_LOCKED and minutes == 0:
            # An open-ended locked session plus a forgotten passcode is the one shape that could
            # genuinely trap someone. Refuse to create it.
            self.error.configure(
                text="A locked session needs an end time — open-ended locked sessions aren't allowed.")
            return

        session = FocusSession(
            task=task, planned_minutes=minutes,
            interval_seconds=clamp_interval(self.interval.get() or DEFAULT_INTERVAL),
            accountability=acc, extra_apps=self._extra_apps, allowed_apps=self._allowed_apps,
            provider_id=self.prefs.provider_id)

        watch = session.watchlist(self.prefs.monitored_apps)
        if not watch:
            self.error.configure(text="No apps are being watched — pick some under 'Apps for "
                                      "this session only', or set a default watchlist.")
            return

        # Remember the answers so next time is one keypress.
        self.prefs.last_task = task
        self.prefs.focus_interval = session.interval_seconds
        self.prefs.focus_minutes = minutes
        self.prefs.focus_accountability = acc

        self.store.start(session)

        from ..service.monitor_service import MonitorService
        MonitorService.shared().start()

        if self.on_started:
            self.on_started(session)
        self.destroy()
