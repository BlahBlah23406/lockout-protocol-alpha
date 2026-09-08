"""Run every Windows test suite.

    python run_tests.py

`python -m unittest discover -s tests -t .` also works, but this script is the documented entry
point because it puts `windows/` on `sys.path` first — every suite imports `guardian.*`, and
without that the discovery run fails with an ImportError that looks like a missing dependency
rather than a path problem.
"""

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

MODULES = [
    "tests.test_guardian",       # frame quality, content-rules parsing, secrets store
    "tests.test_focus",          # sessions, provider wire formats, judgement log
    "tests.test_monitor_flow",   # the monitor loop end to end, with screen + model faked
    "tests.test_ui_smoke",       # every window constructs (skipped when headless)
    "tests.test_policy_contract",  # the learner <-> all-clients format contract
]

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite(loader.loadTestsFromName(m) for m in MODULES)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
