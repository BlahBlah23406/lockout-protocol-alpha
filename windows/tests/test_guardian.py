"""Unit & integration tests for Guardian Windows app.

Mirrors `GuardianTests.swift`: tests FrameQuality heuristics, Ollama verdict parsing,
emulator catalog discovery, DPAPI secrets store, and Ollama Cloud live classification.
"""

import os
import re
import sys
import unittest
from pathlib import Path

# Add windows folder to sys.path
TEST_DIR = Path(__file__).resolve().parent
WINDOWS_DIR = TEST_DIR.parent
sys.path.insert(0, str(WINDOWS_DIR))

from guardian.ai import frame_quality  # noqa: E402
from guardian.ai.ollama_client import OllamaClient, parse_verdict  # noqa: E402
from guardian.capture import emulators, screen_capturer  # noqa: E402
from guardian.models.prefs import Prefs  # noqa: E402
from guardian.models.secrets_store import SecretStore  # noqa: E402


class TestGuardian(unittest.TestCase):

    # ---- FrameQuality ----

    def test_all_black_is_unreadable(self):
        lums = [0] * 1024
        self.assertTrue(frame_quality.is_unreadable_luminance(lums))

    def test_uniform_gray_is_unreadable(self):
        lums = [128] * 1024
        self.assertTrue(frame_quality.is_unreadable_luminance(lums))

    def test_empty_is_unreadable(self):
        self.assertTrue(frame_quality.is_unreadable_luminance([]))

    def test_high_variance_is_readable(self):
        lums = [10 if i % 2 == 0 else 240 for i in range(1024)]
        self.assertFalse(frame_quality.is_unreadable_luminance(lums))

    def test_mostly_black_with_some_content_is_readable(self):
        lums = [0] * 1000
        for i in range(100):
            lums[i] = 200
        self.assertFalse(frame_quality.is_unreadable_luminance(lums))

    # ---- Ollama verdict parsing ----

    def test_parse_violation_true(self):
        body = '{"message":{"content":"{\\"violation\\": true, \\"reason\\": \\"explicit image\\"}"}}'
        v = parse_verdict(body)
        self.assertTrue(v.violation)
        self.assertEqual(v.reason, "explicit image")
        self.assertFalse(v.undetermined)

    def test_parse_violation_false(self):
        body = '{"message":{"content":"{\\"violation\\": false}"}}'
        v = parse_verdict(body)
        self.assertFalse(v.violation)
        self.assertFalse(v.undetermined)

    def test_parse_garbage_is_undetermined(self):
        v = parse_verdict("not json at all")
        self.assertTrue(v.undetermined)
        self.assertFalse(v.violation)

    def test_parse_missing_content_is_undetermined(self):
        v = parse_verdict('{"message":{}}')
        self.assertTrue(v.undetermined)

    # ---- Emulators discovery ----

    def test_emulator_catalog_defined(self):
        self.assertTrue(len(emulators.CATALOG) > 0)
        self.assertTrue(emulators.is_emulator("hd-player.exe"))
        self.assertTrue(emulators.is_emulator("emulator.exe"))

    # ---- Secrets store & Prefs ----

    def test_secret_store_dpapi(self):
        SecretStore.set("test_key", "secret_value_123")
        self.assertEqual(SecretStore.get("test_key"), "secret_value_123")
        SecretStore.delete("test_key")
        self.assertIsNone(SecretStore.get("test_key"))

    def test_no_api_key_is_baked_into_the_source(self):
        """There must be NO fallback key baked into the app.

        This test used to assert the opposite — that a specific key literal was present — because
        an earlier revision shipped a real Ollama Cloud key in `prefs.py` so that first run "just
        worked". That key was in a public repo, which means it was public. It is gone, and this
        test guards against it, or anything like it, coming back.

        It reads the SOURCE rather than the resolved value on purpose. A machine that ran the old
        build still has that key in its DPAPI store, and whether a user has a key configured is
        their business — the defect being guarded is a credential in the repository.
        """
        source = (WINDOWS_DIR / "guardian" / "models" / "prefs.py").read_text(encoding="utf-8")

        self.assertNotIn("670dd2703b9a4b7381a6cefcc", source,
                         "the retired hardcoded API key is back in prefs.py")

        # A generic shape check, so the next hardcoded credential is caught too rather than only
        # this one. Ollama keys are 32 hex chars, a dot, then 24 base62 — distinctive enough to
        # match without flagging ordinary strings.
        self.assertIsNone(re.search(r"[0-9a-f]{32}\.[A-Za-z0-9]{20,}", source),
                          "something shaped like an API key is hardcoded in prefs.py")

    def test_api_key_defaults_to_empty(self):
        """With nothing configured, reading the key yields "" rather than a built-in value.

        Skipped on a machine that has a key stored or in the environment, because there is nothing
        to assert there — the point is only that the app never invents one.
        """
        from guardian.models.prefs import K

        if SecretStore.get(K.ollama_key) or any(
                os.environ.get(v, "").strip()
                for v in ("LOCKOUT_API_KEY", "OLLAMA_CLOUD_KEY", "OLLAMA_API_KEY")):
            self.skipTest("an API key is configured on this machine")
        self.assertEqual(Prefs.shared().ollama_api_key, "")

    # ---- Live integration (opt-in) ----

    @unittest.skipUnless(os.environ.get("LOCKOUT_LIVE_TESTS", "").strip(),
                         "live test: set LOCKOUT_LIVE_TESTS=1 and configure an API key")
    def test_ollama_cloud_evaluation(self):
        """Captures the real screen and sends it to the configured provider.

        Opt-in, because it needs three things a test suite has no right to assume: a display, a
        network, and someone's paid API credit. It was previously unconditional, which meant the
        whole suite failed on CI with "AI quota exhausted" — a red build that says nothing about
        the code. The offline tests cover the parse, retry, fail-over and never-block behaviour;
        this one only answers "does a real round-trip work end to end", which is worth having but
        only when you ask for it.
        """
        p = Prefs.shared()
        img = screen_capturer.capture()
        self.assertIsNotNone(img, "Screen capture failed")

        client = OllamaClient(p)
        cfg = client.config()
        verdict = client.evaluate(img, cfg)

        self.assertFalse(verdict.undetermined, f"Evaluation undetermined: {verdict.reason}")
        self.assertFalse(verdict.transient, f"Evaluation transient error: {verdict.reason}")
        self.assertIsInstance(verdict.violation, bool)


if __name__ == "__main__":
    unittest.main()
