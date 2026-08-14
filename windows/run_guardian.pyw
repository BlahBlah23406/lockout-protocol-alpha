"""Guardian for Windows — Main Application Entry Point.

Mirrors `GuardianApp.swift` / `AppDelegate.swift`:
1. Single instance mutex (`Global\\com.lockoutprotocol.guardian`).
2. DPI awareness.
3. System tray icon (pystray) with status, Open, Start/Stop, and Quit (passcode-protected).
4. Startup sequence: SafetyCovenant check, Emulators sync, MonitorService resume, Persistence,
   TamperGuard, SettingsGuard.
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
from guardian.ui import passcode_prompt, tkroot  # noqa: E402
from guardian.ui.main_window import MainWindow  # noqa: E402

APP_MUTEX = "Global\\" + BUNDLE_ID


def create_icon_image():
    """Generates the LCARS eye logo for the system tray icon."""
    img = Image.new("RGBA", (64, 64), (5, 7, 13, 255))
    draw = ImageDraw.Draw(img)
    # LCARS orange pill + gold center eye
    draw.rounded_rectangle([6, 18, 58, 46], radius=14, fill=(255, 153, 102, 255))
    draw.ellipse([20, 20, 44, 44], fill=(5, 7, 13, 255))
    draw.ellipse([26, 26, 38, 38], fill=(255, 204, 102, 255))
    return img


class GuardianTrayApp:

    def __init__(self, root, main_win):
        self.root = root
        self.main_win = main_win
        self.prefs = Prefs.shared()
        self.monitor = MonitorService.shared()
        self.tray_icon = None

    def start(self):
        icon_img = create_icon_image()
        menu = pystray.Menu(
            pystray.MenuItem("Open Dashboard", self.on_open, default=True),
            pystray.MenuItem("Start / Stop Monitoring", self.on_toggle_monitor),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit Guardian", self.on_quit)
        )
        self.tray_icon = pystray.Icon("Guardian", icon_img, "Guardian — Accountability Monitor", menu)
        notify.set_notifier(self.show_toast)
        threading.Thread(target=self.tray_icon.run, name="guardian-tray", daemon=True).start()

    def show_toast(self, title: str, body: str):
        if self.tray_icon:
            try:
                self.tray_icon.notify(body, title)
            except Exception:
                pass

    def on_open(self, _icon=None, _item=None):
        tkroot.run_on_ui(self.main_win.show_dashboard)

    def on_toggle_monitor(self, _icon=None, _item=None):
        def act():
            if self.monitor.is_running:
                if passcode_prompt.require(self.main_win, "stop Guardian"):
                    self.monitor.stop()
            else:
                self.monitor.start()
        tkroot.run_on_ui(act)

    def on_quit(self, _icon=None, _item=None):
        def act():
            if passcode_prompt.require(self.main_win, "quit Guardian"):
                if self.prefs.monitoring_enabled:
                    tamper_alert.raise_alert(
                        "Guardian was quit on this PC — monitoring is stopped until it relaunches.",
                        force=True)
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
    if Prefs.shared().monitoring_enabled:
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
