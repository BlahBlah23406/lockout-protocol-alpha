"""The monitor loop end to end, with the screen and the model faked out.

The unit tests cover each piece; these cover the wiring, and especially the paths that must NOT
block. Nothing here takes a screenshot, opens a window, or makes a network call.
"""

import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

TEST_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TEST_DIR.parent))

from guardian.ai import providers  # noqa: E402
from guardian.focus import session as session_mod  # noqa: E402
from guardian.models import event_log as event_log_mod  # noqa: E402
from guardian.focus.session import ACC_LOCKED, ACC_SELF, FocusSession, SessionStore  # noqa: E402
from guardian.models import judgements  # noqa: E402
from guardian.service import overrides  # noqa: E402
from guardian.service.monitor_service import MonitorService  # noqa: E402


class MonitorFlowCase(unittest.TestCase):
    """Base fixture: a fresh session store and judgement log in a temp dir, a fake screen showing
    Chrome, a capturable frame, and a stubbed model."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        tmp = Path(self.tmp.name)

        # Including the activity log: otherwise the tests append fake "[BLOCK] Chrome OFF TASK"
        # lines to the real log in the user's AppData.
        for module, attr in ((session_mod, "SESSION_FILE"), (session_mod, "HISTORY_FILE"),
                             (judgements, "JUDGEMENTS_FILE"), (event_log_mod, "LOG_FILE")):
            original = getattr(module, attr)
            setattr(module, attr, tmp / Path(original).name)
            self.addCleanup(lambda m=module, a=attr, o=original: setattr(m, a, o))

        # Process-wide singletons; a fresh one per test stops them leaking between cases.
        SessionStore._instance = None
        MonitorService._instance = None
        self.store = SessionStore.shared()
        self.monitor = MonitorService.shared()
        self.addCleanup(lambda: setattr(SessionStore, "_instance", None))
        self.addCleanup(lambda: setattr(MonitorService, "_instance", None))
        overrides._until.clear()
        event_log_mod.EventLog._instance = None
        self.addCleanup(lambda: setattr(event_log_mod.EventLog, "_instance", None))

        self.prefs = self.monitor._prefs
        self._patch(self.prefs.__class__, "monitored_apps",
                    property(lambda _s: {"chrome.exe"}, lambda _s, _v: None))
        self._patch(self.prefs.__class__, "dry_run",
                    property(lambda _s: False, lambda _s, _v: None))

        # A screen that is on, showing Chrome, and capturable.
        self.enter(mock.patch("guardian.service.monitor_service.screen_state.is_visible",
                              return_value=True))
        self.enter(mock.patch("guardian.service.monitor_service.foreground_app.identifier",
                              return_value="chrome.exe"))
        self.enter(mock.patch("guardian.service.monitor_service.foreground_app.title",
                              return_value="YouTube"))
        self.enter(mock.patch("guardian.service.monitor_service.screen_capturer.capture",
                              return_value=object()))
        self.enter(mock.patch("guardian.service.monitor_service.frame_quality.is_unreadable",
                              return_value=False))
        self.enter(mock.patch("guardian.service.monitor_service.notify_local"))

        # Never actually push, and never actually draw a window.
        self.pushes = []
        self.enter(mock.patch("guardian.service.monitor_service.pusher.send",
                              side_effect=lambda *a, **k: self.pushes.append(a) or None))
        self.blocks = []
        self.enter(mock.patch(
            "guardian.service.monitor_service.BlockController.shared",
            return_value=mock.Mock(is_blocking=False,
                                   show=mock.Mock(side_effect=lambda *a, **k: self.blocks.append((a, k))))))

    def enter(self, patcher):
        patcher.start()
        self.addCleanup(patcher.stop)

    def _patch(self, cls, name, value):
        original = getattr(cls, name)
        setattr(cls, name, value)
        self.addCleanup(lambda: setattr(cls, name, original))

    def stub_model(self, verdict):
        self.enter(mock.patch("guardian.service.monitor_service.providers.evaluate",
                              return_value=verdict))

    def start_session(self, **kw):
        kw.setdefault("task", "revising integration by parts")
        kw.setdefault("planned_minutes", 60)
        return self.store.start(FocusSession(**kw))


class TestNoSessionMeansNoCapture(MonitorFlowCase):

    def test_idle_never_touches_the_screen(self):
        """The README's privacy claim, as a test: with no session, `capture()` is never called."""
        with mock.patch("guardian.service.monitor_service.screen_capturer.capture") as cap, \
             mock.patch.object(type(self.prefs), "content_rules_enabled",
                               property(lambda _s: False)):
            self.monitor._tick()
            cap.assert_not_called()
        self.assertIn("No focus session", self.monitor.status)


class TestOnTaskPath(MonitorFlowCase):

    def test_on_task_is_logged_and_not_blocked(self):
        session = self.start_session()
        self.stub_model(providers.Verdict(on_task=True, confidence=0.9))
        wait = self.monitor._tick()

        self.assertEqual(self.blocks, [])
        self.assertEqual(wait, session.interval_seconds)
        self.assertEqual(self.store.current.checks, 1)
        self.assertEqual(self.store.current.off_task_count, 0)
        rows = judgements.read_all()
        self.assertEqual(rows[-1]["verdict"], "on_task")
        self.assertEqual(rows[-1]["action"], "allowed")

    def test_an_unwatched_app_is_not_checked_at_all(self):
        self.start_session()
        with mock.patch("guardian.service.monitor_service.foreground_app.identifier",
                        return_value="notepad.exe"), \
             mock.patch("guardian.service.monitor_service.providers.evaluate") as ev:
            self.monitor._tick()
            ev.assert_not_called()

    def test_a_session_only_app_is_checked(self):
        """The per-session list reaches the watchlist the loop actually consults."""
        self.start_session(extra_apps={"steam.exe"})
        with mock.patch("guardian.service.monitor_service.foreground_app.identifier",
                        return_value="steam.exe"):
            self.stub_model(providers.Verdict(on_task=True))
            self.monitor._tick()
        self.assertEqual(self.store.current.checks, 1)

    def test_a_session_excused_app_is_skipped(self):
        self.start_session(allowed_apps={"chrome.exe"})
        with mock.patch("guardian.service.monitor_service.providers.evaluate") as ev:
            self.monitor._tick()
            ev.assert_not_called()


class TestOffTaskPath(MonitorFlowCase):

    def test_off_task_blocks_and_records(self):
        self.start_session(accountability=ACC_SELF)
        self.stub_model(providers.Verdict(on_task=False, reason="gaming stream", confidence=0.9))
        self.monitor._tick()

        self.assertEqual(len(self.blocks), 1)
        args, kwargs = self.blocks[0]
        self.assertEqual(args[0], "chrome.exe")
        self.assertIs(kwargs["session"], self.store.current)
        self.assertTrue(kwargs["judgement_id"])
        self.assertEqual(self.store.current.off_task_count, 1)
        self.assertEqual(judgements.read_all()[-1]["action"], "blocked")

    def test_a_self_managed_session_does_not_alert_anyone(self):
        self.start_session(accountability=ACC_SELF)
        self.stub_model(providers.Verdict(on_task=False, reason="shopping"))
        self.monitor._tick()
        self.assertEqual(self.pushes, [])

    def test_a_locked_session_alerts_the_partner(self):
        self.start_session(accountability=ACC_LOCKED)
        self.stub_model(providers.Verdict(on_task=False, reason="shopping"))
        self.monitor._tick()
        self.assertEqual(len(self.pushes), 1)
        title, body = self.pushes[0][1], self.pushes[0][2]
        self.assertIn("Off task", title)
        self.assertIn("shopping", body)

    def test_test_mode_records_but_never_blocks(self):
        self._patch(self.prefs.__class__, "dry_run", property(lambda _s: True, lambda _s, _v: None))
        self.start_session()
        self.stub_model(providers.Verdict(on_task=False, reason="a game"))
        self.monitor._tick()
        self.assertEqual(self.blocks, [])
        self.assertEqual(judgements.read_all()[-1]["action"], "logged")


class TestNothingElseEverBlocks(MonitorFlowCase):
    """Every not-a-clean-off-task path, asserted to leave the user alone."""

    def test_a_busy_backend_does_not_block_and_retries_sooner(self):
        self.start_session()
        self.stub_model(providers.Verdict(reason="AI busy (HTTP 503)",
                                          undetermined=True, transient=True))
        wait = self.monitor._tick()
        self.assertEqual(self.blocks, [])
        self.assertLess(wait, self.store.current.interval_seconds)
        self.assertEqual(self.store.current.checks, 0)      # a non-answer is not a check

    def test_an_unparseable_answer_does_not_block(self):
        self.start_session()
        self.stub_model(providers.Verdict(reason="parse-failed", undetermined=True))
        self.monitor._tick()
        self.assertEqual(self.blocks, [])

    def test_a_capture_failure_does_not_block(self):
        self.start_session()
        with mock.patch("guardian.service.monitor_service.screen_capturer.capture",
                        return_value=None), \
             mock.patch("guardian.service.monitor_service.providers.evaluate") as ev:
            self.monitor._tick()
            ev.assert_not_called()
        self.assertEqual(self.blocks, [])

    def test_a_blank_or_drm_frame_does_not_block(self):
        self.start_session()
        with mock.patch("guardian.service.monitor_service.frame_quality.is_unreadable",
                        return_value=True), \
             mock.patch("guardian.service.monitor_service.providers.evaluate") as ev:
            self.monitor._tick()
            ev.assert_not_called()
        self.assertEqual(self.blocks, [])

    def test_a_sleeping_screen_pauses_instead_of_alerting(self):
        self.start_session()
        with mock.patch("guardian.service.monitor_service.screen_state.is_visible",
                        return_value=False), \
             mock.patch("guardian.service.monitor_service.screen_state.reason",
                        return_value="locked"), \
             mock.patch("guardian.service.monitor_service.screen_capturer.capture") as cap:
            self.monitor._tick()
            cap.assert_not_called()
        self.assertEqual(self.blocks, [])

    def test_an_unidentifiable_foreground_app_does_not_block(self):
        self.start_session()
        with mock.patch("guardian.service.monitor_service.foreground_app.identifier",
                        return_value="?unreadable"), \
             mock.patch("guardian.service.monitor_service.providers.evaluate") as ev:
            for _ in range(6):
                self.monitor._tick()
            ev.assert_not_called()
        self.assertEqual(self.blocks, [])

    def test_an_active_override_suppresses_checks(self):
        self.start_session()
        overrides.grant("chrome.exe", seconds=60)
        with mock.patch("guardian.service.monitor_service.providers.evaluate") as ev:
            self.monitor._tick()
            ev.assert_not_called()

    def test_a_paused_session_is_not_checked(self):
        self.start_session()
        self.store.pause(120)
        with mock.patch("guardian.service.monitor_service.providers.evaluate") as ev:
            wait = self.monitor._tick()
            ev.assert_not_called()
        self.assertGreater(wait, 0)


class TestCadence(MonitorFlowCase):

    def test_the_interval_is_respected_between_checks_on_one_app(self):
        """Switching away and back must not force a check storm."""
        self.start_session(interval_seconds=300)
        self.stub_model(providers.Verdict(on_task=True))
        self.monitor._tick()
        self.assertEqual(self.store.current.checks, 1)

        with mock.patch("guardian.service.monitor_service.providers.evaluate") as ev:
            self.monitor._tick()
            self.monitor._tick()
            ev.assert_not_called()
        self.assertEqual(self.store.current.checks, 1)

    def test_a_newly_focused_app_is_checked_immediately(self):
        """A new app must not inherit the previous app's countdown."""
        self.start_session(interval_seconds=300, extra_apps={"steam.exe"})
        self.stub_model(providers.Verdict(on_task=True))
        self.monitor._tick()
        with mock.patch("guardian.service.monitor_service.foreground_app.identifier",
                        return_value="steam.exe"):
            self.monitor._tick()
        self.assertEqual(self.store.current.checks, 2)


class TestSessionLifecycle(MonitorFlowCase):

    def test_an_expired_session_ends_itself_and_is_archived(self):
        """Expiry is evaluated on read, so a laptop that slept past the end time still ends."""
        session = self.start_session(planned_minutes=30)
        session.started_at = time.time() - 31 * 60
        self.store._save()
        self.assertIsNone(self.store.current)
        self.assertEqual(len(self.store.history()), 1)
        self.assertEqual(self.store.history()[0].ended_reason, "time's up")

    def test_a_session_survives_a_restart(self):
        """Force-quitting must not silently cancel a locked session."""
        self.start_session(accountability=ACC_LOCKED, task="write the essay")
        SessionStore._instance = None
        revived = SessionStore.shared().current
        self.assertIsNotNone(revived)
        self.assertEqual(revived.task, "write the essay")
        self.assertEqual(revived.accountability, ACC_LOCKED)

    def test_ending_a_session_stops_all_watching(self):
        self.start_session()
        self.store.end("ended by user")
        with mock.patch("guardian.service.monitor_service.screen_capturer.capture") as cap, \
             mock.patch.object(type(self.prefs), "content_rules_enabled",
                               property(lambda _s: False)):
            self.monitor._tick()
            cap.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
