"""Construct every window offscreen, to catch widget-call typos the logic tests can't.

A smoke test, not a UI test: it proves the screens build, not that they look right. Skipped where
there is no display.
"""

import sys
import unittest
from pathlib import Path

TEST_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TEST_DIR.parent))

try:
    import tkinter as tk
    _root = tk.Tk()
    _root.withdraw()
    HAVE_DISPLAY = True
except Exception:                     # headless CI, no Tcl/Tk installed
    HAVE_DISPLAY = False
    _root = None

if HAVE_DISPLAY:
    from guardian.focus.session import ACC_LOCKED, FocusSession
    from guardian.ui import tkroot
    from guardian.ui.app_picker_view import AppPickerWindow
    from guardian.ui.block_view import build as build_block
    from guardian.ui.focus_start_view import FocusStartWindow
    from guardian.ui.main_window import MainWindow
    from guardian.ui.quick_panel import QuickPanel
    from guardian.ui.settings_view import SettingsWindow

# Far enough off-screen that nothing flashes in front of whoever is running the tests.
OFFSCREEN = "+4000+4000"


@unittest.skipUnless(HAVE_DISPLAY, "no display available")
class TestWindowsConstruct(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.root = _root
        cls.root.geometry(OFFSCREEN)
        tkroot.set_root(cls.root)

    def _built(self, window):
        """Force a layout pass; most widget-option errors only fire during geometry work."""
        self.root.update_idletasks()
        self.addCleanup(lambda: self._safe_destroy(window))
        return window

    @staticmethod
    def _safe_destroy(window):
        try:
            window.destroy()
        except Exception:
            pass

    def test_dashboard(self):
        self._built(MainWindow(self.root))

    def test_focus_start(self):
        self._built(FocusStartWindow(self.root))

    def test_quick_panel(self):
        self._built(QuickPanel(self.root))

    def test_settings(self):
        self._built(SettingsWindow(self.root))

    def test_app_picker_editing_defaults(self):
        self._built(AppPickerWindow(self.root))

    def test_app_picker_scoped_to_a_session(self):
        self._built(AppPickerWindow(self.root, selection={"a.exe"}, on_done=lambda _s: None,
                                    title="Apps for this session"))

    def _block(self, session):
        w = tk.Toplevel(self.root)
        w.geometry(OFFSCREEN)
        build_block(w, "Chrome", "gaming stream", lambda: None, lambda: None, focus=False,
                    session=session, on_false_alarm=lambda: None)
        return self._built(w)

    def test_block_screen_self_managed(self):
        self._block(FocusSession("math test prep", planned_minutes=60))

    def test_block_screen_locked(self):
        self._block(FocusSession("math test prep", planned_minutes=60,
                                 accountability=ACC_LOCKED))

    def test_block_screen_without_a_session(self):
        """The content-rules path has no session object and still has to render."""
        self._block(None)


if __name__ == "__main__":
    unittest.main(verbosity=2)
