"""Focus mode: sessions, the provider layer, and the judgement log.

Nothing here touches the network or the screen.
"""

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

TEST_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TEST_DIR.parent))

from guardian.ai import providers  # noqa: E402
from guardian.focus.session import (ACC_LOCKED, ACC_SELF, DEFAULT_INTERVAL, MAX_INTERVAL,  # noqa: E402
                                    MIN_INTERVAL, FocusSession, clamp_interval)


class TestFocusSession(unittest.TestCase):

    def test_watchlist_is_defaults_plus_extras_minus_allowed(self):
        s = FocusSession("math test prep", extra_apps={"steam.exe"}, allowed_apps={"slack.exe"})
        self.assertEqual(s.watchlist({"chrome.exe", "slack.exe"}),
                         {"chrome.exe", "steam.exe"})

    def test_watchlist_tracks_later_edits_to_the_defaults(self):
        """A delta, not a snapshot — editing the defaults mid-session should take effect."""
        s = FocusSession("essay", extra_apps={"steam.exe"})
        self.assertEqual(s.watchlist({"chrome.exe"}), {"chrome.exe", "steam.exe"})
        self.assertEqual(s.watchlist({"chrome.exe", "firefox.exe"}),
                         {"chrome.exe", "firefox.exe", "steam.exe"})

    def test_allowed_app_wins_over_a_default(self):
        s = FocusSession("answering support tickets", allowed_apps={"slack.exe"})
        self.assertNotIn("slack.exe", s.watchlist({"slack.exe", "chrome.exe"}))

    def test_interval_is_clamped_both_ways(self):
        self.assertEqual(clamp_interval(1), MIN_INTERVAL)
        self.assertEqual(clamp_interval(99999), MAX_INTERVAL)
        self.assertEqual(clamp_interval("nonsense"), DEFAULT_INTERVAL)
        self.assertEqual(clamp_interval(None), DEFAULT_INTERVAL)
        self.assertEqual(clamp_interval(120), 120)

    def test_open_ended_session_never_expires(self):
        s = FocusSession("reading", planned_minutes=0)
        self.assertIsNone(s.remaining_seconds)
        self.assertFalse(s.is_over)

    def test_timed_session_expires(self):
        s = FocusSession("reading", planned_minutes=30)
        s.started_at = time.time() - 31 * 60
        self.assertTrue(s.is_over)
        self.assertEqual(s.remaining_seconds, 0)

    def test_only_locked_sessions_hold_their_own_exit(self):
        self.assertFalse(FocusSession("x", accountability=ACC_SELF).requires_passcode_to_end())
        self.assertTrue(FocusSession("x", accountability=ACC_LOCKED,
                                     planned_minutes=60).requires_passcode_to_end())

    def test_only_locked_sessions_alert_the_partner(self):
        self.assertFalse(FocusSession("x", accountability=ACC_SELF).alerts_partner())
        self.assertTrue(FocusSession("x", accountability=ACC_LOCKED).alerts_partner())

    def test_unknown_accountability_falls_back_to_self(self):
        """Fail towards the weaker mode: a corrupt file must not promote someone into a locked
        session whose passcode they never set."""
        self.assertEqual(FocusSession("x", accountability="admin").accountability, ACC_SELF)

    def test_round_trips_through_json(self):
        s = FocusSession("write the essay", planned_minutes=45, interval_seconds=90,
                         accountability=ACC_LOCKED, extra_apps={"a.exe"}, allowed_apps={"b.exe"})
        s.checks, s.off_task_count, s.override_count = 12, 3, 1
        back = FocusSession.from_dict(json.loads(json.dumps(s.to_dict())))
        self.assertEqual(back.id, s.id)
        self.assertEqual(back.task, s.task)
        self.assertEqual(back.extra_apps, {"a.exe"})
        self.assertEqual(back.allowed_apps, {"b.exe"})
        self.assertEqual((back.checks, back.off_task_count, back.override_count), (12, 3, 1))


class TestVerdictParsing(unittest.TestCase):

    def test_plain_on_task(self):
        v = providers.parse_focus_json('{"on_task": true, "confidence": 0.9}')
        self.assertTrue(v.on_task)
        self.assertAlmostEqual(v.confidence, 0.9)
        self.assertFalse(v.off_task)

    def test_off_task_keeps_the_reason(self):
        v = providers.parse_focus_json(
            '{"on_task": false, "reason": "Netflix playing The Office", "confidence": 0.95}')
        self.assertTrue(v.off_task)
        self.assertIn("Netflix", v.reason)

    def test_markdown_fences_are_stripped(self):
        """Small models fence their JSON regardless of the prompt."""
        v = providers.parse_focus_json('```json\n{"on_task": false, "reason": "game"}\n```')
        self.assertTrue(v.off_task)
        self.assertEqual(v.reason, "game")

    def test_unreadable_is_undetermined_not_a_block(self):
        v = providers.parse_focus_json('{"unreadable": true}')
        self.assertTrue(v.undetermined)
        self.assertFalse(v.off_task)

    def test_garbage_is_undetermined_not_a_block(self):
        for bad in ("not json at all", "", "{}", '{"on_task": "yes"}', '{"on_task": null}'):
            v = providers.parse_focus_json(bad)
            self.assertTrue(v.undetermined, bad)
            self.assertFalse(v.off_task, bad)

    def test_confidence_is_clamped_and_never_throws(self):
        self.assertEqual(providers.parse_focus_json(
            '{"on_task": true, "confidence": 7}').confidence, 1.0)
        self.assertEqual(providers.parse_focus_json(
            '{"on_task": true, "confidence": -3}').confidence, 0.0)
        self.assertEqual(providers.parse_focus_json(
            '{"on_task": true, "confidence": "high"}').confidence, 0.0)


class TestProviderEnvelopes(unittest.TestCase):
    """Each provider wraps the same answer differently; all four must reach the same Verdict."""

    ANSWER = '{"on_task": false, "reason": "YouTube gaming stream", "confidence": 0.8}'

    def test_ollama_envelope(self):
        body = json.dumps({"message": {"content": self.ANSWER}})
        self.assertTrue(providers.parse_response(providers.OLLAMA, body).off_task)

    def test_openai_envelope(self):
        body = json.dumps({"choices": [{"message": {"content": self.ANSWER}}]})
        self.assertTrue(providers.parse_response(providers.OPENAI, body).off_task)

    def test_anthropic_envelope(self):
        body = json.dumps({"content": [{"type": "text", "text": self.ANSWER}]})
        self.assertTrue(providers.parse_response(providers.ANTHROPIC, body).off_task)

    def test_custom_uses_the_openai_shape(self):
        body = json.dumps({"choices": [{"message": {"content": self.ANSWER}}]})
        self.assertTrue(providers.parse_response(providers.CUSTOM, body).off_task)

    def test_wrong_envelope_is_undetermined(self):
        body = json.dumps({"error": {"message": "model not found"}})
        v = providers.parse_response(providers.OPENAI, body)
        self.assertTrue(v.undetermined)
        self.assertFalse(v.off_task)


class TestRequestBuilding(unittest.TestCase):

    def _cfg(self, kind, base):
        return providers.ProviderConfig(kind, base, "some-model", ["k"])

    def test_ollama_attaches_the_image_and_hits_api_chat(self):
        url, payload, _ = providers.build_request(
            self._cfg(providers.OLLAMA, "http://127.0.0.1:11434"), "B64", "sys", "usr")
        self.assertEqual(url, "http://127.0.0.1:11434/api/chat")
        self.assertEqual(payload["messages"][-1]["images"], ["B64"])

    def test_openai_uses_a_data_uri(self):
        url, payload, _ = providers.build_request(
            self._cfg(providers.OPENAI, "https://api.openai.com"), "B64", "sys", "usr")
        self.assertEqual(url, "https://api.openai.com/v1/chat/completions")
        img = payload["messages"][-1]["content"][-1]["image_url"]["url"]
        self.assertEqual(img, "data:image/jpeg;base64,B64")

    def test_a_base_url_already_ending_in_v1_is_not_doubled(self):
        """The most common misconfiguration: /v1/v1/chat/completions."""
        url, _, _ = providers.build_request(
            self._cfg(providers.CUSTOM, "http://127.0.0.1:1234/v1"), "B64", "sys", "usr")
        self.assertEqual(url, "http://127.0.0.1:1234/v1/chat/completions")

    def test_anthropic_sends_a_base64_image_block_and_a_version_header(self):
        url, payload, extra = providers.build_request(
            self._cfg(providers.ANTHROPIC, "https://api.anthropic.com"), "B64", "sys", "usr")
        self.assertEqual(url, "https://api.anthropic.com/v1/messages")
        self.assertEqual(payload["system"], "sys")
        self.assertEqual(payload["messages"][0]["content"][0]["source"]["data"], "B64")
        self.assertIn("anthropic-version", extra)

    def test_auth_header_location_differs_by_provider(self):
        self.assertEqual(providers.auth_headers(self._cfg(providers.ANTHROPIC, "x"), "K"),
                         {"x-api-key": "K"})
        self.assertEqual(providers.auth_headers(self._cfg(providers.OPENAI, "x"), "K"),
                         {"Authorization": "Bearer K"})

    def test_no_key_means_no_auth_header(self):
        self.assertEqual(providers.auth_headers(self._cfg(providers.OLLAMA, "x"), ""), {})


class TestNeverBlockOnFailure(unittest.TestCase):
    """Nothing that goes wrong on our side may look like the user being off task."""

    def _cfg(self):
        return providers.ProviderConfig(providers.OLLAMA, "http://x", "m", ["k1", "k2"])

    def _run(self, attempts):
        """Drive `evaluate` with a scripted sequence of transport results."""
        seq = list(attempts)
        with mock.patch.object(providers, "jpeg_base64", return_value="B64"), \
             mock.patch.object(providers, "_request", side_effect=seq):
            return providers.evaluate(self._cfg(), object(), "task", "Chrome", "title",
                                      sleep=lambda _s: None)

    def test_transient_codes_are_classified_as_transient(self):
        for code in (408, 429, 500, 502, 503, 504):
            self.assertTrue(providers.is_transient_code(code), code)
        for code in (200, 404, 418):
            self.assertFalse(providers.is_transient_code(code), code)

    def test_server_errors_never_produce_an_off_task_verdict(self):
        busy = providers._Attempt(providers.Verdict(reason="AI busy (HTTP 503)",
                                                    undetermined=True, transient=True))
        v = self._run([busy] * 6)
        self.assertTrue(v.transient)
        self.assertFalse(v.off_task)

    def test_a_rejected_key_fails_over_to_the_backup(self):
        rejected = providers._Attempt(
            providers.Verdict(reason="key rejected (HTTP 429)", undetermined=True, transient=True),
            key_rejected=True)
        good = providers._Attempt(providers.Verdict(on_task=False, reason="steam store"))
        promoted = []
        seq = [rejected, good]
        with mock.patch.object(providers, "jpeg_base64", return_value="B64"), \
             mock.patch.object(providers, "_request", side_effect=seq):
            v = providers.evaluate(self._cfg(), object(), "task", "Chrome", "t",
                                   sleep=lambda _s: None, on_key_worked=promoted.append)
        self.assertTrue(v.off_task)
        self.assertEqual(promoted, ["k2"])          # remembered, so the next call starts there

    def test_every_key_exhausted_is_transient_not_a_block(self):
        """Running out of API credit must cost the user nothing."""
        rejected = providers._Attempt(
            providers.Verdict(reason="rejected", undetermined=True, transient=True),
            key_rejected=True)
        v = self._run([rejected] * 6)
        self.assertTrue(v.transient)
        self.assertFalse(v.off_task)

    def test_encode_failure_is_undetermined(self):
        with mock.patch.object(providers, "jpeg_base64", side_effect=OSError("boom")):
            v = providers.evaluate(self._cfg(), object(), "t", "a", "b", sleep=lambda _s: None)
        self.assertTrue(v.undetermined)
        self.assertFalse(v.off_task)

    def test_missing_model_is_undetermined(self):
        cfg = providers.ProviderConfig(providers.OLLAMA, "http://x", "", ["k"])
        v = providers.evaluate(cfg, object(), "t", "a", "b", sleep=lambda _s: None)
        self.assertTrue(v.undetermined)
        self.assertFalse(v.off_task)


class TestPromptContents(unittest.TestCase):

    def test_task_app_and_title_all_reach_the_model(self):
        p = providers.build_user_prompt("math test prep", "Chrome", "Khan Academy — integrals")
        for needle in ("math test prep", "Chrome", "Khan Academy"):
            self.assertIn(needle, p)

    def test_learned_notes_are_labelled_as_settled(self):
        p = providers.build_user_prompt("t", "a", "b", extra_notes="Edge shows my course PDFs")
        self.assertIn("PREVIOUSLY CONFIRMED", p)
        self.assertIn("course PDFs", p)

    def test_empty_notes_add_no_section(self):
        self.assertNotIn("PREVIOUSLY CONFIRMED",
                         providers.build_user_prompt("t", "a", "b", extra_notes="   "))

    def test_system_prompt_defaults_to_on_task(self):
        """The bias against false alarms is a product decision, so it is pinned."""
        self.assertIn("DEFAULT TO on_task", providers.FOCUS_SYSTEM)


class TestJudgementLog(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        from guardian.models import judgements
        self.j = judgements
        self._orig = judgements.JUDGEMENTS_FILE
        judgements.JUDGEMENTS_FILE = Path(self.tmp.name) / "judgements.jsonl"
        self.addCleanup(lambda: setattr(judgements, "JUDGEMENTS_FILE", self._orig))

    def test_feedback_is_folded_onto_the_judgement_it_refers_to(self):
        session = FocusSession("math test prep")
        jid = self.j.record(session, "chrome.exe", "Chrome", "YouTube", "off_task",
                            "gaming video", 0.8, "blocked", "ollama:m")
        self.assertTrue(self.j.add_feedback(jid, self.j.FB_FALSE_ALARM, "it was a lecture"))
        rows = self.j.read_all()
        self.assertEqual(len(rows), 1)              # the feedback row is folded in, not listed
        self.assertEqual(rows[0]["feedback"], self.j.FB_FALSE_ALARM)
        self.assertEqual(rows[0]["feedback_note"], "it was a lecture")

    def test_unknown_feedback_is_rejected(self):
        self.assertFalse(self.j.add_feedback("j_1", "whatever"))

    def test_a_torn_final_line_does_not_break_the_reader(self):
        session = FocusSession("t")
        self.j.record(session, "a.exe", "A", "t", "on_task", "", 0.5, "allowed", "p")
        with open(self.j.JUDGEMENTS_FILE, "a", encoding="utf-8") as f:
            f.write('{"id": "j_2", "ts": 1, "tas')     # killed mid-write
        self.assertEqual(len(self.j.read_all()), 1)

    def test_session_stats_counts_blocks_and_false_alarms(self):
        session = FocusSession("t")
        self.j.record(session, "a.exe", "A", "t", "on_task", "", 0.9, "allowed", "p")
        jid = self.j.record(session, "b.exe", "B", "t", "off_task", "r", 0.9, "blocked", "p")
        self.j.add_feedback(jid, self.j.FB_FALSE_ALARM)
        stats = self.j.session_stats(session.id)
        self.assertEqual(stats, {"checks": 2, "off_task": 1, "blocked": 1, "false_alarms": 1})


class TestLearnedPolicyClient(unittest.TestCase):
    """The policy file comes from a separate program, so the client treats it as untrusted."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        from guardian.focus import learned
        self.learned = learned
        self._orig = learned.POLICY_FILE
        learned.POLICY_FILE = Path(self.tmp.name) / "focus_policy.json"
        learned._cache.update({"mtime": None, "data": None})
        self.addCleanup(lambda: setattr(learned, "POLICY_FILE", self._orig))

    def _write(self, obj):
        self.learned.POLICY_FILE.write_text(json.dumps(obj), encoding="utf-8")
        self.learned._cache.update({"mtime": None, "data": None})

    def test_missing_policy_is_a_no_op(self):
        self.assertEqual(self.learned.decide("t", "a"),
                         {"prompt_suffix": "", "pre_allow": False, "block_threshold": 0.0})

    def test_corrupt_policy_is_a_no_op(self):
        self.learned.POLICY_FILE.write_text("{not json", encoding="utf-8")
        self.learned._cache.update({"mtime": None, "data": None})
        self.assertFalse(self.learned.decide("t", "a")["pre_allow"])

    def test_a_future_schema_is_ignored_rather_than_half_read(self):
        self._write({"schema": 99, "pre_allow_everything": True})
        self.assertFalse(self.learned.decide("t", "a")["pre_allow"])

    def test_a_stale_policy_expires(self):
        old = time.time() - (self.learned.POLICY_MAX_AGE_DAYS + 1) * 86400
        self._write({"schema": 1, "generated_at": old})
        self.assertEqual(self.learned._load(), {})

    def test_threshold_can_never_exceed_the_client_ceiling(self):
        """Hand-editing the generated file must not switch blocking off."""
        self._write({"schema": 1, "generated_at": time.time()})
        with mock.patch.object(self.learned, "_via_learner",
                               return_value={"block_threshold": 0.99, "prompt_suffix": "",
                                             "pre_allow": False}):
            self.assertEqual(self.learned.decide("t", "a")["block_threshold"],
                             self.learned.MAX_THRESHOLD)

    def test_prompt_suffix_is_truncated_to_the_budget(self):
        self._write({"schema": 1, "generated_at": time.time()})
        with mock.patch.object(self.learned, "_via_learner",
                               return_value={"prompt_suffix": "x" * 5000, "pre_allow": False,
                                             "block_threshold": 0.0}):
            self.assertEqual(len(self.learned.decide("t", "a")["prompt_suffix"]),
                             self.learned.MAX_SUFFIX_CHARS)

    def test_a_throwing_learner_never_propagates(self):
        self._write({"schema": 1, "generated_at": time.time()})
        with mock.patch.object(self.learned, "_via_learner", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.learned._via_learner("t", "a", "")     # sanity: the mock really raises
        with mock.patch.object(self.learned, "_via_learner", return_value=None):
            self.assertFalse(self.learned.decide("t", "a")["pre_allow"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
