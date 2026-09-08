"""Guardian for Windows — Main Application Entry Point.

Mirrors `GuardianApp.swift` / `AppDelegate.swift`:
1. Single instance mutex (`Global\\com.lockoutprotocol.guardian`).
2. DPI awareness.
3. System tray icon (pystray) whose primary action is the mini panel — start a focus session,
   see the one running, end it. The full dashboard is the secondary action.
4. Startup sequence: SafetyCovenant check, Emulators sync, MonitorService resume, Persistence,
   TamperGuard, SettingsGuard.

The tray icon is the product's front door on Windows, so it changes colour with state: grey when
no session is running (and therefore nothing is being captured), green during a self-managed
session, red during a locked one. Being able to tell at a glance whether you are being watched is
not a nicety for a tool like this.
"""

import os
import sys
import threading
import tkinter as tk
from pathlib import Path

from PIL import Image, ImageDraw
import pystray

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from guardian import notify, win32  # noqa: E402
from guardian.models.event_log import EventLog  # noqa: E402
from guardian.models.prefs import Prefs  # noqa: E402
from guardian.paths import BUNDLE_ID  # noqa: E402
from guardian.service import persistence  # noqa: E402
from guardian.service import safety_covenant, tamper_alert, tamper_guard  # noqa: E402
from guardian.service.monitor_service import MonitorService  # noqa: E402
from guardian.service.settings_guard import SettingsGuard  # noqa: E402
from guardian.capture import emulators  # noqa: E402
from guardian.focus.session import ACC_LOCKED, SessionStore  # noqa: E402
from guardian.models import judgements  # noqa: E402
from guardian.ui import passcode_prompt, tkroot  # noqa: E402
from guardian.ui.focus_start_view import FocusStartWindow  # noqa: E402
from guardian.ui.main_window import MainWindow  # noqa: E402
from guardian.ui.quick_panel import QuickPanel  # noqa: E402

APP_MUTEX = "Global\\" + BUNDLE_ID


# Tray icon colours by state. The eye is deliberately DARK and closed-looking when idle: the icon
# should never suggest it is watching at a moment when it is not.
_IDLE = (140, 140, 160, 255)
_SELF = (154, 230, 201, 255)
_LOCKED = (224, 83, 61, 255)


def create_icon_image(state: str = "idle"):
    """The LCARS eye, tinted by monitoring state (idle / self / locked)."""
    ring = {"self": _SELF, "locked": _LOCKED}.get(state, _IDLE)
    img = Image.new("RGBA", (64, 64), (5, 7, 13, 255))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([6, 18, 58, 46], radius=14, fill=ring)
    draw.ellipse([20, 20, 44, 44], fill=(5, 7, 13, 255))
    if state == "idle":
        # Idle: a closed eye — a flat bar rather than a pupil.
        draw.rectangle([26, 31, 38, 34], fill=ring)
    else:
        draw.ellipse([26, 26, 38, 38], fill=(255, 204, 102, 255))
    return img


class GuardianTrayApp:

    def __init__(self, root, main_win):
        self.root = root
        self.main_win = main_win
        self.prefs = Prefs.shared()
        self.monitor = MonitorService.shared()
        self.sessions = SessionStore.shared()
        self.tray_icon = None
        self.panel = None
        self._icon_state = None

    def start(self):
        menu = pystray.Menu(
            # Left-click lands here: the mini panel, not the dashboard. Starting a session is the
            # thing people came to do, and it should be one click away.
            pystray.MenuItem("Focus panel", self.on_panel, default=True),
            pystray.MenuItem("Start a focus session…", self.on_new_session),
            pystray.MenuItem("End session", self.on_end_session,
                             visible=lambda _i: self.sessions.is_active),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open dashboard", self.on_open),
            pystray.MenuItem("Quit", self.on_quit),
        )
        self.tray_icon = pystray.Icon("Lockout Protocol", create_icon_image("idle"),
                                      "Lockout Protocol — no session", menu)
        notify.set_notifier(self.show_toast)
        threading.Thread(target=self.tray_icon.run, name="guardian-tray", daemon=True).start()

        # Keep the icon honest about what is happening. Polled rather than event-driven because
        # the session can also end on its own (time's up), which fires no user event.
        self.sessions.subscribe(self.refresh_icon)
        self._schedule_icon_refresh()

    # ---- icon state ---------------------------------------------------------------------

    def _schedule_icon_refresh(self):
        self.refresh_icon()
        self.root.after(5000, self._schedule_icon_refresh)

    def refresh_icon(self):
        session = self.sessions.current
        if session is None:
            state, tip = "idle", "Lockout Protocol — no session, nothing watched"
        else:
            state = "locked" if session.accountability == ACC_LOCKED else "self"
            left = session.remaining_seconds
            when = "open-ended" if left is None else f"{int(left // 60)}m left"
            tip = f"Lockout Protocol — {session.task[:40]} ({when})"
        if self.tray_icon is None or state == self._icon_state:
            if self.tray_icon is not None:
                self.tray_icon.title = tip
            return
        self._icon_state = state
        try:
            self.tray_icon.icon = create_icon_image(state)
            self.tray_icon.title = tip
        except Exception:
            pass

    def show_toast(self, title: str, body: str):
        if self.tray_icon:
            try:
                self.tray_icon.notify(body, title)
            except Exception:
                pass

    # ---- menu actions -------------------------------------------------------------------

    def on_panel(self, _icon=None, _item=None):
        def act():
            if self.panel is None or not self.panel.winfo_exists():
                self.panel = QuickPanel.shared(self.root, on_open_dashboard=self.main_win.show_dashboard)
            self.panel.toggle()
        tkroot.run_on_ui(act)

    def on_new_session(self, _icon=None, _item=None):
        tkroot.run_on_ui(lambda: FocusStartWindow(self.root, on_started=lambda _s: self.refresh_icon()))

    def on_end_session(self, _icon=None, _item=None):
        def act():
            session = self.sessions.current
            if session is None:
                return
            if session.requires_passcode_to_end() and not passcode_prompt.require(
                    self.main_win, "end this locked session"):
                return
            self.sessions.end("ended by user")
            self.monitor.stop()
            self.refresh_icon()
        tkroot.run_on_ui(act)

    def on_open(self, _icon=None, _item=None):
        tkroot.run_on_ui(self.main_win.show_dashboard)

    def on_quit(self, _icon=None, _item=None):
        def act():
            # Quitting mid-session is the one bypass we cannot technically prevent, so a locked
            # session makes it cost the passcode and tells the partner on the way out.
            session = self.sessions.current
            gate = "quit during a locked session" if (
                session is not None and session.requires_passcode_to_end()) else "quit"
            if passcode_prompt.require(self.main_win, gate):
                if session is not None and session.alerts_partner():
                    tamper_alert.raise_alert(
                        f"Lockout Protocol was quit on this PC during a locked session "
                        f"(\"{session.task}\") — monitoring stopped.", force=True)
                elif self.prefs.monitoring_enabled:
                    tamper_alert.raise_alert(
                        "Lockout Protocol was quit on this PC — monitoring is stopped until it "
                        "relaunches.", force=True)
                if self.tray_icon:
                    self.tray_icon.stop()
                self.root.quit()
        tkroot.run_on_ui(act)


def main():
    # 1. Single instance check
    _, already_running = win32.single_instance_mutex(APP_MUTEX)
    if already_running:
        print("Guardian is already running.")
        sys.exit(0)

    # 2. DPI Awareness
    win32.set_dpi_aware()

    # 3. Root Tk window (hidden container for dialogs and MainWindow)
    root = tk.Tk()
    root.withdraw()
    tkroot.set_root(root)

    # 4. Main dashboard window
    main_win = MainWindow(root)

    # 5. System tray app
    tray_app = GuardianTrayApp(root, main_win)
    tray_app.start()

    # 6. Startup sequence (matches Mac AppDelegate.applicationDidFinishLaunching)
    safety_covenant.check()
    emulators.sync_monitored_apps()
    judgements.trim()
    # Resume a session that was running when we were last killed. Without this, force-quitting the
    # app would silently cancel a locked session, which would make "locked" worth nothing.
    if SessionStore.shared().is_active or Prefs.shared().monitoring_enabled:
        MonitorService.shared().start()
    persistence.apply()
    tamper_guard.TamperGuard.shared().start()
    SettingsGuard.shared().start()

    # 7. Start UI event loop
    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
