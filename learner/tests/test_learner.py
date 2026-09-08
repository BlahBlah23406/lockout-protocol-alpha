"""Unit tests for the focus learner.

    python -m unittest discover learner/tests          (from the repo root)

What is tested here is deliberately skewed towards the parts that are dangerous to get wrong
rather than the parts that are easy to test. The feature extraction gets covered because every
other mechanism keys off it; the anti-gaming guard and the expiry get covered because they are
the only things standing between a learning feature and a user quietly disabling their own
accountability tool; and the calibration arithmetic gets covered because a sign error there would
be invisible in the aggregate metrics and catastrophic in effect.
"""

import json
import os
import tempfile
import time
import unittest

from learner import features as F
from learner import learn as L
from learner import policy as P
from learner import store


DAY = 86400.0
# A fixed base time so day-bucketing is deterministic. Midday local, so adding whole days never
# straddles a boundary regardless of the machine's timezone or DST.
BASE = time.mktime((2026, 3, 2, 12, 0, 0, 0, 0, -1))


def judgement(ts, task="working on math test prep", app="chrome.exe", app_name="Chrome",
              title="Integration by parts - Khan Academy", verdict="off_task",
              confidence=0.7, action="blocked", jid=None, **extra):
    row = {
        "id": jid or ("j_%d" % int(ts * 1000)),
        "ts": ts,
        "session_id": "fs_test",
        "task": task,
        "app": app,
        "app_name": app_name,
        "window_title": title,
        "verdict": verdict,
        "reason": "test",
        "confidence": confidence,
        "action": action,
        "provider": "test",
        "feedback": None,
        "feedback_at": None,
        "feedback_note": None,
    }
    row.update(extra)
    return row


def with_feedback(row, kind, delay=20.0):
    """Attach feedback the way the producer does: folded, as `store.fold` would deliver it."""
    out = dict(row)
    out["feedback"] = kind
    out["feedback_at"] = row["ts"] + delay
    out["feedback_note"] = ""
    return out


def confirmed(n_days, per_day=2, delay=20.0, **kw):
    """`n_days` days of `per_day` confirmed false alarms on one signature."""
    rows = []
    for d in range(n_days):
        for i in range(per_day):
            ts = BASE + d * DAY + i * 600.0
            rows.append(with_feedback(judgement(ts, **kw), "false_alarm", delay))
    return rows


class TestFeatures(unittest.TestCase):

    def test_stemming_collapses_task_phrasings(self):
        self.assertEqual(F.task_keywords("studying for my math test"),
                         F.task_keywords("study for math tests"))

    def test_generic_verbs_are_stopwords(self):
        # "work"/"working" carry no topic signal and merged unrelated task families when they
        # were left in. This is the regression test for that.
        self.assertNotIn("work", F.task_keywords("working on math test prep"))
        self.assertNotIn("afternoon", F.task_keywords("job applications this afternoon"))

    def test_digits_are_dropped_from_titles(self):
        # The changing part of a title must never reach a signature key.
        a = F.title_pattern("essay draft 3.docx - Word")
        b = F.title_pattern("essay draft 7.docx - Word")
        self.assertEqual(a, b)

    def test_title_pattern_is_stable_across_visits(self):
        a = F.title_pattern("Integration by parts - Khan Academy")
        b = F.title_pattern("Trig substitution explained - Khan Academy")
        self.assertEqual(a, b)
        self.assertEqual(a["kind"], "domain")
        self.assertEqual(a["value"], "khanacademy.org")

    def test_domain_prefers_the_title_tail(self):
        # The hole this closes: scanning the whole title first calls a Khan Academy video on
        # YouTube "khanacademy.org", which routes it around the never-pre-allow list.
        self.assertEqual(
            F.extract_domain("Integration by parts | Khan Academy - YouTube"), "youtube.com")
        self.assertEqual(
            F.extract_domain("Integration by parts - Khan Academy"), "khanacademy.org")

    def test_literal_domain_wins_over_brand_name(self):
        self.assertEqual(F.extract_domain("khanacademy.org/math - Chrome"), "khanacademy.org")

    def test_unknown_title_falls_back_to_tokens(self):
        pattern = F.title_pattern("quarterly-forecast.xlsx - Excel")
        self.assertEqual(pattern["kind"], "tokens")
        self.assertIn("forecast", pattern["value"])

    def test_empty_title_degrades_to_app_pattern(self):
        self.assertEqual(F.title_pattern("")["kind"], "app")

    def test_overlap_is_containment_not_jaccard(self):
        small, big = ("math", "test"), ("math", "test", "prep", "revision")
        self.assertAlmostEqual(F.overlap(small, big), 1.0)
        self.assertAlmostEqual(F.jaccard(small, big), 0.5)
        self.assertEqual(F.overlap((), big), 0.0)

    def test_clusterer_merges_phrasings_of_one_task(self):
        clusterer = F.TaskClusterer.from_tasks([
            "working on math test prep",
            "studying for my math test",
            "math revision for the calculus exam",
        ])
        self.assertEqual(len(clusterer.clusters), 1)

    def test_clusterer_keeps_unrelated_tasks_apart(self):
        clusterer = F.TaskClusterer.from_tasks([
            "working on math test prep", "coding the payments service", "applying for jobs"])
        self.assertEqual(len(clusterer.clusters), 3)

    def test_unknown_task_matches_nothing(self):
        clusterer = F.TaskClusterer.from_tasks(["working on math test prep"])
        cluster, _ = clusterer.match("repainting the shed")
        self.assertEqual(cluster, "tc_none")

    def test_signature_key_is_a_stable_string(self):
        pattern = {"kind": "domain", "value": "khanacademy.org"}
        self.assertEqual(F.signature_key("tc_abc", "chrome.exe", pattern),
                         "tc_abc|chrome.exe|domain:khanacademy.org")

    def test_tod_bucket_boundaries(self):
        def at(hour):
            return F.tod_bucket(time.mktime((2026, 3, 2, hour, 30, 0, 0, 0, -1)))
        self.assertEqual(at(3), "night")
        self.assertEqual(at(9), "morning")
        self.assertEqual(at(14), "afternoon")
        self.assertEqual(at(20), "evening")
        self.assertEqual(at(23), "late")


class TestStore(unittest.TestCase):
    """The reader has one job it must never fail at: surviving a damaged file."""

    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)

    def tearDown(self):
        try:
            os.unlink(self.path)
        except OSError:
            pass

    def write(self, text):
        with open(self.path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)

    def test_folds_separate_feedback_rows(self):
        rows = [judgement(BASE, jid="j_1"),
                {"id": "j_1#fb", "ts": BASE + 30, "ref": "j_1", "feedback": "false_alarm",
                 "feedback_at": BASE + 30, "feedback_note": "textbook video"}]
        store.write_rows(self.path, rows)
        result = store.read_judgements(self.path)
        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.rows[0]["feedback"], "false_alarm")
        self.assertEqual(result.rows[0]["feedback_note"], "textbook video")
        self.assertAlmostEqual(result.rows[0]["feedback_at"], BASE + 30)

    def test_last_feedback_press_wins(self):
        rows = [judgement(BASE, jid="j_1"),
                {"id": "a", "ts": BASE + 10, "ref": "j_1", "feedback": "false_alarm"},
                {"id": "b", "ts": BASE + 20, "ref": "j_1", "feedback": "correct"}]
        store.write_rows(self.path, rows)
        self.assertEqual(store.read_judgements(self.path).rows[0]["feedback"], "correct")

    def test_feedback_before_its_judgement_still_folds(self):
        # Happens when two logs are concatenated. Order on disk must not matter.
        rows = [{"id": "x", "ts": BASE + 30, "ref": "j_1", "feedback": "missed"},
                judgement(BASE, jid="j_1")]
        store.write_rows(self.path, rows)
        self.assertEqual(store.read_judgements(self.path).rows[0]["feedback"], "missed")

    def test_malformed_lines_are_skipped_not_fatal(self):
        good = json.dumps(judgement(BASE, jid="j_1"))
        self.write("﻿" + good + "\nnot json at all\n{\"truncated\": \n\n# comment\n")
        result = store.read_judgements(self.path)
        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.skipped, 2)

    def test_orphan_feedback_is_counted_not_dropped_silently(self):
        rows = [judgement(BASE, jid="j_1"),
                {"id": "z", "ts": BASE, "ref": "j_missing", "feedback": "false_alarm"}]
        store.write_rows(self.path, rows)
        self.assertEqual(store.read_judgements(self.path).orphan_feedback, 1)

    def test_missing_file_returns_empty(self):
        result = store.read_judgements(self.path + ".nope")
        self.assertEqual(len(result.rows), 0)

    def test_string_confidence_is_repaired_not_discarded(self):
        row = judgement(BASE, jid="j_1")
        row["confidence"] = "0.7"
        row["verdict"] = "OFF_TASK"
        store.write_rows(self.path, [row])
        got = store.read_judgements(self.path).rows[0]
        self.assertAlmostEqual(got["confidence"], 0.7)
        self.assertEqual(got["verdict"], "off_task")

    def test_unknown_enum_values_fail_closed(self):
        row = judgement(BASE, jid="j_1", verdict="probably_fine", action="nuked")
        store.write_rows(self.path, [row])
        got = store.read_judgements(self.path).rows[0]
        self.assertEqual(got["verdict"], "unreadable")   # never silently "on_task"
        self.assertEqual(got["action"], "logged")

    def test_extra_keys_survive_the_round_trip(self):
        store.write_rows(self.path, [judgement(BASE, jid="j_1", truth_on_task=True)])
        self.assertTrue(store.read_judgements(self.path).rows[0]["truth_on_task"])


class TestAntiGamingGuard(unittest.TestCase):

    def state(self, rows, **guard_kw):
        return L.learn(rows, guard=L.GuardConfig(**guard_kw) if guard_kw else None)

    def test_one_press_never_creates_an_allowance(self):
        rows = [with_feedback(judgement(BASE), "false_alarm")]
        self.assertEqual(L.allowances(self.state(rows)), [])

    def test_evidence_must_span_separate_days(self):
        # Five presses in one sitting: enough raw count, wrong shape. Guard 4.
        one_day = confirmed(n_days=1, per_day=5)
        self.assertEqual(L.allowances(self.state(one_day)), [])
        spread = confirmed(n_days=3, per_day=1)
        self.assertEqual(len(L.allowances(self.state(spread))), 1)

    def test_reflex_presses_are_not_credited(self):
        # Guard 2: faster than a human can read the block screen.
        rows = confirmed(n_days=3, per_day=2, delay=1.0)
        state = self.state(rows)
        self.assertEqual(state.stats["false_alarms_credited"], 0)
        self.assertEqual(state.stats["false_alarms_rejected"], 6)
        self.assertEqual(L.allowances(state), [])

    def test_per_signature_cap_stops_accumulation(self):
        # Guard 3: 40 presses on one signature bank no more than the cap.
        rows = confirmed(n_days=20, per_day=2)
        state = self.state(rows)
        sig = list(state.signatures.values())[0]
        self.assertEqual(sig.credited, state.guard.max_evidence_per_signature)
        self.assertGreater(sig.rejected, 0)

    def test_daily_rate_limit(self):
        # Guard 1: distinct signatures so the per-signature cap is not what bites.
        rows = []
        for i in range(20):
            rows.extend(confirmed(n_days=1, per_day=1,
                                  title="Doc number %s alpha - Word" % chr(ord("a") + i),
                                  app="winword.exe", app_name="Word"))
        state = self.state(rows, max_credited_fa_per_day=5)
        self.assertEqual(state.stats["false_alarms_credited"], 5)
        self.assertEqual(state.stats["false_alarms_rejected"], 15)

    def test_correct_feedback_subtracts_from_evidence(self):
        # Guard 5. Three confirmations then two "actually you were right" presses.
        rows = confirmed(n_days=3, per_day=1)
        for d in (3, 4):
            rows.append(with_feedback(judgement(BASE + d * DAY), "correct"))
        state = self.state(rows)
        sig = list(state.signatures.values())[0]
        self.assertEqual(sig.credited, 3)
        self.assertEqual(sig.net_evidence, 1)
        self.assertEqual(L.allowances(state), [])

    def test_missed_feedback_revokes_an_allowance_outright(self):
        rows = confirmed(n_days=4, per_day=2)
        self.assertEqual(len(L.allowances(self.state(rows))), 1)
        rows.append(with_feedback(judgement(BASE + 5 * DAY), "missed"))
        self.assertEqual(L.allowances(self.state(rows)), [])

    def test_missed_feedback_is_never_rate_limited(self):
        # Asking to be stopped MORE must never be throttled, whatever else is happening.
        rows = [with_feedback(judgement(BASE + i * 60.0, jid="j_m%d" % i), "missed")
                for i in range(30)]
        state = self.state(rows, max_credited_fa_per_day=1)
        self.assertEqual(state.stats["missed"], 30)

    def test_leisure_domains_can_only_be_downgraded(self):
        # Guard 8: YouTube can stop blocking, but the check still runs and is still logged.
        rows = confirmed(n_days=4, per_day=2,
                         title="Integration by parts | Khan Academy - YouTube")
        allow = L.allowances(self.state(rows))
        self.assertEqual(len(allow), 1)
        self.assertEqual(allow[0]["action"], "downgrade")
        self.assertEqual(allow[0]["pattern"]["value"], "youtube.com")

    def test_specific_non_leisure_domain_earns_a_pre_allow(self):
        rows = confirmed(n_days=4, per_day=2, title="Integration by parts - Khan Academy")
        allow = L.allowances(self.state(rows))
        self.assertEqual(allow[0]["action"], "pre_allow")

    def test_whole_app_patterns_can_only_be_downgraded(self):
        # A pattern this broad would allow every window of the app, so it never skips the check.
        rows = confirmed(n_days=4, per_day=2, title="", app="game.exe", app_name="Game")
        allow = L.allowances(self.state(rows))
        self.assertEqual(allow[0]["action"], "downgrade")

    def test_spamming_trips_the_integrity_alert(self):
        rows = []
        for d in range(12):
            for i in range(14):
                ts = BASE + d * DAY + i * 300.0
                rows.append(with_feedback(
                    judgement(ts, title="For You - TikTok", confidence=0.95,
                              jid="j_%d_%d" % (d, i)),
                    "false_alarm", delay=1.0))
        state = self.state(rows)
        self.assertTrue(state.integrity.notify_partner)
        self.assertGreater(state.integrity.score, 0.6)
        self.assertTrue(state.integrity.headline)

    def test_honest_feedback_does_not_trip_the_alert(self):
        # The regression that matters most: an alert that cries wolf is worse than no alert.
        rows = confirmed(n_days=6, per_day=2, delay=25.0)
        state = self.state(rows)
        self.assertFalse(state.integrity.notify_partner)


class TestExpiry(unittest.TestCase):

    def test_allowance_is_not_emitted_after_its_ttl(self):
        rows = confirmed(n_days=4, per_day=2)
        fresh = L.learn(rows)
        self.assertEqual(len(L.allowances(fresh)), 1)
        stale = L.learn(rows, now=BASE + 4 * DAY + 40 * DAY)
        self.assertEqual(L.allowances(stale), [])

    def test_apply_enforces_expiry_even_on_an_old_policy_file(self):
        # A policy that is never recompiled must still decay on the client.
        state = L.learn(confirmed(n_days=4, per_day=2))
        pol = P.compile_policy(state)
        args = dict(task="working on math test prep", app="chrome.exe",
                    title="Integration by parts - Khan Academy")
        self.assertTrue(P.apply(pol, ts=BASE + 5 * DAY, **args)["pre_allow"])
        self.assertFalse(P.apply(pol, ts=BASE + 60 * DAY, **args)["pre_allow"])

    def test_evidence_outside_the_window_is_ignored(self):
        old = confirmed(n_days=4, per_day=2)
        state = L.learn(old, config=L.LearnConfig(window_days=2.0), now=BASE + 100 * DAY)
        self.assertEqual(state.stats["in_window"], 0)


class TestCalibration(unittest.TestCase):

    def setUp(self):
        self.config = L.LearnConfig()

    def threshold(self, fa=0, missed=0):
        th = L.ThresholdState("tc_x", "chrome.exe")
        th.credited_fa = fa
        th.missed = missed
        return L.threshold_for(th, self.config)

    def test_base_with_no_evidence(self):
        self.assertAlmostEqual(self.threshold(), 0.55)

    def test_false_alarms_raise_the_bar(self):
        self.assertAlmostEqual(self.threshold(fa=1), 0.60)
        self.assertAlmostEqual(self.threshold(fa=4), 0.75)

    def test_missed_lowers_it_twice_as_fast(self):
        self.assertAlmostEqual(self.threshold(missed=1), 0.45)
        self.assertAlmostEqual(self.threshold(fa=2, missed=1), 0.55)

    def test_ceiling_is_never_exceeded(self):
        # Guard 7. No number of presses can turn blocking off.
        for fa in (6, 20, 500, 10000):
            self.assertLessEqual(self.threshold(fa=fa), self.config.threshold_ceiling)
        self.assertAlmostEqual(self.threshold(fa=10000), 0.85)

    def test_floor_is_never_breached(self):
        self.assertAlmostEqual(self.threshold(missed=100), 0.30)

    def test_client_ceiling_matches_the_learner_ceiling(self):
        # If these ever drift, the offline evaluation stops measuring the shipped product.
        self.assertAlmostEqual(self.config.threshold_ceiling, P.MAX_THRESHOLD)

    def test_thresholds_need_more_than_a_single_press(self):
        rows = [with_feedback(judgement(BASE), "false_alarm")]
        self.assertEqual(L.thresholds(L.learn(rows)), [])


class TestPolicyApply(unittest.TestCase):

    def setUp(self):
        rows = confirmed(n_days=4, per_day=2)
        rows += confirmed(n_days=4, per_day=2,
                          title="r/learnmath - stuck on this - Reddit")
        self.state = L.learn(rows)
        self.pol = P.compile_policy(self.state)

    def apply(self, task="working on math test prep", app="chrome.exe",
              title="Integration by parts - Khan Academy"):
        return P.apply(self.pol, task=task, app=app, title=title, ts=BASE + 3 * DAY)

    def test_return_shape_is_exactly_the_client_contract(self):
        result = self.apply()
        self.assertEqual(set(result), {"prompt_suffix", "pre_allow", "block_threshold"})
        self.assertIsInstance(result["prompt_suffix"], str)
        self.assertIsInstance(result["pre_allow"], bool)
        self.assertIsInstance(result["block_threshold"], float)

    def test_policy_carries_the_fields_the_client_status_line_reads(self):
        for key in ("schema", "generated_at", "exemplar_count", "signature_count"):
            self.assertIn(key, self.pol)
        self.assertEqual(self.pol["schema"], 1)

    def test_known_signature_is_pre_allowed(self):
        self.assertTrue(self.apply()["pre_allow"])

    def test_leisure_signature_is_downgraded_not_skipped(self):
        result = self.apply(title="r/learnmath - stuck on this - Reddit")
        self.assertFalse(result["pre_allow"])
        self.assertAlmostEqual(result["block_threshold"], P.MAX_THRESHOLD)

    def test_a_different_task_does_not_inherit_the_allowance(self):
        result = self.apply(task="playing video games")
        self.assertFalse(result["pre_allow"])
        self.assertEqual(result["prompt_suffix"], "")
        self.assertEqual(result["block_threshold"], 0.0)

    def test_a_different_screen_in_the_same_app_is_still_checked(self):
        self.assertFalse(self.apply(title="For You - TikTok")["pre_allow"])

    def test_empty_policy_means_no_learning(self):
        self.assertEqual(P.apply({}, task="x", app="y", title="z"),
                         {"prompt_suffix": "", "pre_allow": False, "block_threshold": 0.0})

    def test_wrong_schema_is_refused_entirely(self):
        future = dict(self.pol, schema=99)
        self.assertFalse(P.apply(future, task="working on math test prep",
                                 app="chrome.exe", title="x")["pre_allow"])

    def test_prompt_suffix_respects_the_budget(self):
        result = self.apply()
        self.assertLessEqual(len(result["prompt_suffix"]), P.MAX_SUFFIX_CHARS)
        self.assertIn("khanacademy.org", result["prompt_suffix"])

    def test_prompt_suffix_never_exceeds_a_tiny_budget(self):
        cluster, _ = P.match_cluster(self.pol, "working on math test prep")
        text = P.build_prompt_suffix(self.pol, "working on math test prep", cluster, budget=60)
        self.assertLessEqual(len(text), 60)

    def test_explain_produces_a_trace(self):
        result = P.explain(self.pol, task="working on math test prep", app="chrome.exe",
                           title="Integration by parts - Khan Academy", ts=BASE + 3 * DAY)
        self.assertTrue(any("RESULT:" in line for line in result["trace"]))
        self.assertEqual(result["decision"], self.apply())

    def test_stale_policy_files_are_refused_by_the_loader(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        try:
            old = dict(self.pol, generated_at=time.time() - 90 * DAY)
            P.save_policy(path, old)
            self.assertEqual(P.load_policy(path), {})
            P.save_policy(path, dict(self.pol, generated_at=time.time()))
            self.assertEqual(P.load_policy(path).get("schema"), 1)
        finally:
            os.unlink(path)

    def test_compile_is_deterministic(self):
        again = P.compile_policy(L.learn(confirmed(n_days=4, per_day=2)
                                         + confirmed(n_days=4, per_day=2,
                                                     title="r/learnmath - stuck on this - Reddit")))
        self.assertEqual(json.dumps(again, sort_keys=True),
                         json.dumps(self.pol, sort_keys=True))


class TestExemplars(unittest.TestCase):

    def test_line_matches_the_prompt_section_wording(self):
        state = L.learn(confirmed(n_days=4, per_day=2))
        sig = list(state.signatures.values())[0]
        line = L.exemplar_line(sig)
        # The prompt heading is "PREVIOUSLY CONFIRMED BY THE USER -- treat these as settled",
        # so a line has to read as a settled statement, not an instruction.
        self.assertTrue(line.startswith("- "))
        self.assertIn("is part of this task", line)
        self.assertIn("khanacademy.org", line)

    def test_contradicted_signatures_never_reach_the_prompt(self):
        rows = confirmed(n_days=4, per_day=2)
        rows.append(with_feedback(judgement(BASE + 5 * DAY), "missed"))
        self.assertEqual(L.exemplars(L.learn(rows)), [])

    def test_exemplars_are_scoped_to_their_task_cluster(self):
        rows = confirmed(n_days=4, per_day=2)
        rows += confirmed(n_days=4, per_day=2, task="coding the payments service",
                          title="idempotency keys - Stack Overflow")
        pol = P.compile_policy(L.learn(rows))
        maths = P.apply(pol, task="working on math test prep", app="chrome.exe",
                        title="x", ts=BASE + 3 * DAY)["prompt_suffix"]
        self.assertIn("khanacademy.org", maths)
        self.assertNotIn("stackoverflow.com", maths)


class TestDecisionsMap(unittest.TestCase):
    """The pre-expanded table the Swift and Kotlin clients read instead of calling `apply()`."""

    def setUp(self):
        rows = confirmed(n_days=4, per_day=2)
        rows += confirmed(n_days=4, per_day=2, task="studying for my math test")
        rows += confirmed(n_days=4, per_day=2, task="coding the payments service",
                          title="idempotency keys - Stack Overflow")
        self.pol = P.compile_policy(L.learn(rows))

    def test_lookup_key_matches_the_swift_rules(self):
        # Lowercase, non-alphanumerics to spaces, Swift stopwords out, words of <=2 chars out,
        # first four joined with "-". These cases are lifted straight from LearnedPolicy.swift.
        self.assertEqual(P.lookup_key("working on math test prep", "chrome.exe"),
                         "math-test-prep|chrome.exe")
        self.assertEqual(P.lookup_key("Do the C++ homework, in a bit!", "code.exe"),
                         "homework-bit|code.exe")
        self.assertEqual(P.lookup_key("one two three four five six", "a.exe"),
                         "one-two-three-four|a.exe")
        self.assertEqual(P.lookup_key("", "a.exe"), "|a.exe")

    def test_every_observed_phrasing_gets_its_own_key(self):
        # The Swift key has no stemmer, so one cluster must appear under each phrasing it saw.
        keys = self.pol["decisions"]
        self.assertIn("math-test-prep|chrome.exe", keys)
        self.assertIn("studying-math-test|chrome.exe", keys)
        self.assertEqual(keys["math-test-prep|chrome.exe"]["pre_allow"],
                         keys["studying-math-test|chrome.exe"]["pre_allow"])

    def test_pre_allow_always_carries_title_patterns(self):
        # The clients refuse a pre_allow with no title evidence; emitting one would be a silent
        # no-op at best and an app-wide un-watch at worst.
        for key, entry in self.pol["decisions"].items():
            if entry["pre_allow"]:
                self.assertTrue(entry["title_patterns"], "%s pre-allows with no patterns" % key)

    def test_title_patterns_are_anchored_to_the_title_tail(self):
        entry = self.pol["decisions"]["math-test-prep|chrome.exe"]
        self.assertTrue(entry["pre_allow"])
        # Anchored: the Khan Academy pattern must NOT match a Khan Academy video ON YouTube,
        # because `apply()` treats that as a YouTube page and refuses to skip the check.
        self.assertTrue(any(p in "integration by parts - khan academy"
                            for p in entry["title_patterns"]))
        self.assertFalse(any(p in "integration by parts | khan academy - youtube"
                             for p in entry["title_patterns"]))

    def test_decision_for_agrees_with_apply_on_a_known_screen(self):
        args = dict(task="working on math test prep", app="chrome.exe",
                    title="Integration by parts - Khan Academy")
        mapped = P.decision_for(self.pol, **args)
        direct = P.apply(self.pol, ts=BASE + 3 * DAY, **args)
        self.assertEqual(mapped["pre_allow"], direct["pre_allow"])
        self.assertEqual(mapped["prompt_suffix"], direct["prompt_suffix"])

    def test_no_wildcard_rows_are_emitted(self):
        for key in self.pol["decisions"]:
            self.assertFalse(key.startswith("*|"), "wildcard row %s would fire on unseen tasks"
                                                   % key)

    def test_unknown_task_gets_nothing_from_the_map(self):
        self.assertEqual(P.decision_for(self.pol, task="repainting the shed", app="chrome.exe",
                                        title="Dulux - B&Q"),
                         {"prompt_suffix": "", "pre_allow": False, "block_threshold": 0.0})

    def test_decisions_map_is_never_looser_than_apply(self):
        """The invariant that lets three platforms share one file.

        Over an entire simulated log: the map may be stricter than `apply()` (it cannot express
        title-scoped downgrades), but it must never pre-allow a screen `apply()` would check, and
        never return a higher threshold than `apply()` returns.
        """
        from learner import simulate as S
        rows = S.generate(S.SimConfig(days=10, seed=3))
        judged = [r for r in rows if not r.get("ref")]
        state = L.learn(store.fold(rows)[0])
        pol = P.compile_policy(state)

        checked = 0
        for r in judged:
            args = dict(task=r["task"], app=r["app"], title=r["window_title"])
            mapped = P.decision_for(pol, **args)
            direct = P.apply(pol, ts=r["ts"], **args)
            if mapped["pre_allow"]:
                self.assertTrue(direct["pre_allow"],
                                "map pre-allows what apply() would check: %r" % (args,))
            self.assertLessEqual(mapped["block_threshold"], direct["block_threshold"] + 1e-9,
                                 "map is looser than apply(): %r" % (args,))
            checked += 1
        self.assertGreater(checked, 200)


class TestEndToEnd(unittest.TestCase):

    def test_simulate_learn_apply_round_trip(self):
        from learner import simulate as S
        rows = S.generate(S.SimConfig(days=6, seed=7))
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
        try:
            store.write_rows(path, rows)
            read = store.read_judgements(path)
            self.assertEqual(read.skipped, 0)
            self.assertTrue(any(r["feedback"] for r in read.rows))
            pol = P.compile_policy(L.learn(read.rows))
            self.assertEqual(pol["schema"], 1)
            for r in read.rows[:50]:
                result = P.apply(pol, task=r["task"], app=r["app"],
                                 title=r["window_title"], ts=r["ts"])
                self.assertEqual(set(result),
                                 {"prompt_suffix", "pre_allow", "block_threshold"})
                self.assertLessEqual(result["block_threshold"], P.MAX_THRESHOLD)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
