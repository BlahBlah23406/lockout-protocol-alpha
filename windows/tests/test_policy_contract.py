"""The cross-platform contract between the learner and the four clients.

`focus_policy.json` is produced by offline Python and consumed by Python (Windows), Swift (macOS,
iOS) and Kotlin (Android). Nothing compiles all four together, so nothing catches a drift in the
shared format except a test like this one.

The bug that motivated it: the learner lower-cased the app id when writing a lookup key, and the
Swift client didn't. On Windows that was invisible — `chrome.exe` is already lower-case — but on
macOS the bundle id is `com.google.Chrome`, so *every* lookup missed and learning silently did
nothing on one whole platform. Nobody would have noticed for months.

So these tests read the OTHER platforms' source as text and assert the constants agree. That is
unusual, and it is the point: the alternative is a contract that only breaks in production.
"""

import json
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path

TEST_DIR = Path(__file__).resolve().parent
WINDOWS_DIR = TEST_DIR.parent
REPO_ROOT = WINDOWS_DIR.parent
sys.path.insert(0, str(WINDOWS_DIR))
sys.path.insert(0, str(REPO_ROOT))

SWIFT_POLICY = REPO_ROOT / "macos" / "Guardian" / "Focus" / "LearnedPolicy.swift"
KOTLIN_POLICY = (REPO_ROOT / "android" / "app" / "src" / "main" / "java" / "com" /
                 "lockoutprotocol" / "guardian" / "focus" / "LearnedPolicy.kt")

try:
    from learner import policy as learner_policy
    HAVE_LEARNER = True
except Exception:
    HAVE_LEARNER = False


def swift_source() -> str:
    return SWIFT_POLICY.read_text(encoding="utf-8") if SWIFT_POLICY.exists() else ""


def kotlin_source() -> str:
    return KOTLIN_POLICY.read_text(encoding="utf-8") if KOTLIN_POLICY.exists() else ""


@unittest.skipUnless(HAVE_LEARNER, "learner package not present")
class TestLookupKeyAgreement(unittest.TestCase):
    """The key format has to match character for character or a lookup silently misses."""

    CASES = [
        ("working on math test prep", "chrome.exe", "math-test-prep|chrome.exe"),
        ("applying for jobs", "chrome.exe", "applying-jobs|chrome.exe"),
        ("coding the payments service", "code.exe", "coding-payments-service|code.exe"),
        # More than four significant words: truncated to four.
        ("revising integration by parts for Friday's calculus test", "chrome.exe",
         "revising-integration-parts-friday|chrome.exe"),
        # Punctuation becomes a separator; "a" and "of" are stopwords; "an" too.
        ("essay on the industrial revolution", "winword.exe",
         "essay-industrial-revolution|winword.exe"),
    ]

    def test_python_side_matches_the_expected_format(self):
        for task, app, expected in self.CASES:
            self.assertEqual(learner_policy.lookup_key(task, app), expected, task)

    def test_app_id_is_lower_cased(self):
        """The bug this file exists for. A macOS bundle id has uppercase in it."""
        self.assertEqual(learner_policy.lookup_key("math test prep", "com.google.Chrome"),
                         "math-test-prep|com.google.chrome")

    def test_swift_client_lower_cases_the_app_too(self):
        src = swift_source()
        if not src:
            self.skipTest("macOS source not present")
        self.assertRegex(src, r"app\s*\.trimmingCharacters\(in: \.whitespaces\)\s*\.lowercased\(\)",
                         "Swift lookupKey must lower-case the app id")

    def test_kotlin_client_lower_cases_the_app_too(self):
        src = kotlin_source()
        if not src:
            self.skipTest("Android source not present")
        self.assertIn("lowercase()", src)

    def test_stopword_lists_are_identical_across_clients(self):
        expected = set("the a an my for on to of and in working work doing do some this that".split())
        self.assertEqual(set(learner_policy.LOOKUP_STOPWORDS), expected,
                         "learner stopwords drifted")

        for label, src in (("Swift", swift_source()), ("Kotlin", kotlin_source())):
            if not src:
                continue
            # Swift writes the list as `["the", "a", ...]`, Kotlin as `setOf("the", "a", ...)`, so
            # the terminator differs. Matching either is the point: this test exists to catch a
            # drift in the WORDS, and it must not fail merely because a port spells a set
            # differently — nor silently pass because it couldn't find the literal at all.
            match = re.search(r'"the",\s*"a",\s*"an",(.*?)[\]\)]', src, re.S)
            self.assertIsNotNone(match, f"{label}: could not find the stopword literal")
            words = set(re.findall(r'"([a-z]+)"', '"the", "a", "an",' + match.group(1)))
            self.assertEqual(words, expected, f"{label} stopwords drifted from the learner's")

    def test_word_limits_agree(self):
        self.assertEqual(learner_policy.LOOKUP_MAX_WORDS, 4)
        self.assertEqual(learner_policy.LOOKUP_MIN_WORD_LEN, 3)
        for label, src in (("Swift", swift_source()), ("Kotlin", kotlin_source())):
            if not src:
                continue
            self.assertIn("prefix(4)" if label == "Swift" else "take(4)", src,
                          f"{label}: first-four-words rule missing")
            self.assertRegex(src, r"count > 2|length > 2",
                             f"{label}: two-character-word rule missing")


@unittest.skipUnless(HAVE_LEARNER, "learner package not present")
class TestPolicyArtefactShape(unittest.TestCase):
    """The fields every client reads must be present and the right type."""

    @classmethod
    def setUpClass(cls):
        path = REPO_ROOT / "learner" / "data" / "focus_policy.json"
        if not path.exists():
            raise unittest.SkipTest("no compiled policy — run `python -m learner.cli learn` first")
        cls.policy = json.loads(path.read_text(encoding="utf-8"))

    def test_carries_the_fields_the_clients_require(self):
        for field in ("schema", "generated_at", "exemplar_count", "signature_count", "decisions"):
            self.assertIn(field, self.policy, field)
        self.assertEqual(self.policy["schema"], 1)
        self.assertIsInstance(self.policy["generated_at"], (int, float))
        self.assertIsInstance(self.policy["decisions"], dict)

    def test_every_decision_key_is_a_valid_lookup_key(self):
        for key in self.policy["decisions"]:
            self.assertIn("|", key, key)
            task_part, app_part = key.split("|", 1)
            self.assertEqual(app_part, app_part.lower(), f"app part not lower-cased: {key}")
            self.assertLessEqual(len(task_part.split("-")), 4, f"more than 4 words: {key}")

    def test_every_decision_has_the_expected_field_types(self):
        for key, entry in self.policy["decisions"].items():
            self.assertIsInstance(entry.get("prompt_suffix", ""), str, key)
            self.assertIsInstance(entry.get("pre_allow", False), bool, key)
            threshold = entry.get("block_threshold", 0.0)
            self.assertIsInstance(threshold, (int, float), key)
            self.assertGreaterEqual(threshold, 0.0, key)
            self.assertLessEqual(threshold, 1.0, key)

    def test_a_pre_allow_always_carries_title_evidence(self):
        """The clients refuse a `pre_allow` with no title patterns, because an app-wide pre-allow
        would silently un-watch a whole app. Assert the learner never emits one."""
        for key, entry in self.policy["decisions"].items():
            if entry.get("pre_allow"):
                self.assertTrue(entry.get("title_patterns"),
                                f"{key}: pre_allow with no title_patterns")

    def test_prompt_suffixes_fit_the_client_budget(self):
        from guardian.focus import learned
        for key, entry in self.policy["decisions"].items():
            self.assertLessEqual(len(entry.get("prompt_suffix", "")),
                                 learned.MAX_SUFFIX_CHARS, key)

    def test_no_threshold_exceeds_the_client_ceiling(self):
        from guardian.focus import learned
        for key, entry in self.policy["decisions"].items():
            self.assertLessEqual(entry.get("block_threshold", 0.0), learned.MAX_THRESHOLD, key)


@unittest.skipUnless(HAVE_LEARNER, "learner package not present")
class TestWindowsClientReadsRealPolicy(unittest.TestCase):
    """End to end: a policy the learner actually produced, read by the shipping client."""

    def setUp(self):
        source = REPO_ROOT / "learner" / "data" / "focus_policy.json"
        if not source.exists():
            self.skipTest("no compiled policy")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

        from guardian.focus import learned
        self.learned = learned
        self._orig = learned.POLICY_FILE
        target = Path(self.tmp.name) / "focus_policy.json"

        policy = json.loads(source.read_text(encoding="utf-8"))
        # The client expires anything older than 60 days; keep the fixture fresh.
        policy["generated_at"] = time.time()
        target.write_text(json.dumps(policy), encoding="utf-8")

        learned.POLICY_FILE = target
        learned._cache.update({"mtime": None, "data": None})
        self.addCleanup(lambda: setattr(learned, "POLICY_FILE", self._orig))
        self.policy = policy

    def test_the_client_loads_it_rather_than_rejecting_it(self):
        self.assertNotEqual(self.learned._load(), {},
                            "the shipping client rejected a policy the learner produced")

    def test_status_line_reports_real_counts(self):
        status = self.learned.status()
        self.assertIn("exemplar", status)
        self.assertNotIn("no policy learned yet", status)

    def test_a_learned_key_produces_a_decision(self):
        key = next(iter(self.policy["decisions"]), None)
        if key is None:
            self.skipTest("policy has no decisions")
        task_part, app = key.split("|", 1)
        task = task_part.replace("-", " ")
        decision = self.learned.decide(task, app, "linkedin.com")
        for field in ("prompt_suffix", "pre_allow", "block_threshold"):
            self.assertIn(field, decision)
        self.assertLessEqual(decision["block_threshold"], self.learned.MAX_THRESHOLD)

    def test_an_unknown_task_gets_no_learning(self):
        decision = self.learned.decide("something nobody has ever done", "nosuchapp.exe")
        self.assertFalse(decision["pre_allow"])
        self.assertEqual(decision["prompt_suffix"], "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
