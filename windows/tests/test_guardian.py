"""Unit & integration tests for Guardian Windows app.

Mirrors `GuardianTests.swift`: tests FrameQuality heuristics, Ollama verdict parsing,
emulator catalog discovery, DPAPI secrets store, and Ollama Cloud live classification.
"""

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

    def test_ollama_api_key_loaded(self):
        p = Prefs.shared()
        key = p.ollama_api_key
        self.assertTrue(len(key) > 0, "Ollama API key must be initialized")
        self.assertIn("670dd2703b9a4b7381a6cefcc1680982", key)

    # ---- Ollama Cloud Vision Integration ----

    def test_ollama_cloud_evaluation(self):
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
