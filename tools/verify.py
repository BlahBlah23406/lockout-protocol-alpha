"""Run every check that can run on this machine, and say honestly what was skipped.

    python tools/verify.py

Four platforms in four languages means no single command can verify everything anywhere. What this
does instead is run whatever the current machine is capable of and print a scorecard that
distinguishes three outcomes, because collapsing them is how a project ends up believing it is
tested when it isn't:

    PASS     actually ran, actually passed
    FAIL     actually ran, actually failed
    SKIP     could not run here, and why

A green run on Windows means the Windows app and the learner are genuinely tested and the
macOS/iOS Swift is structurally sound. It does NOT mean the Swift compiles — only Xcode can say
that, and it says so in the SKIP line rather than being quietly omitted.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class Check:
    def __init__(self, name, argv, cwd=None, needs=None, skip_reason=None, env=None):
        self.name = name
        self.argv = argv
        self.cwd = cwd or ROOT
        self.needs = needs or (lambda: True)
        self.skip_reason = skip_reason
        self.env = env


def have(tool):
    return shutil.which(tool) is not None


def android_toolchain():
    """The Android build needs a JDK and an SDK. Both are found by env var, the way Gradle does."""
    java = os.environ.get("JAVA_HOME")
    sdk = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    return bool(java and sdk and Path(java, "bin").exists() and Path(sdk).exists())


# An absolute path, because `subprocess` on Windows will not find a `.bat` via a bare name even
# with `cwd` set, and a relative "./gradlew" is not resolvable there either.
GRADLE = str(ROOT / "android" / ("gradlew.bat" if os.name == "nt" else "gradlew"))

CHECKS = [
    Check("windows · unit + integration + UI (92 tests)",
          [sys.executable, "run_tests.py"], cwd=ROOT / "windows"),

    Check("learner · unit tests (71 tests)",
          [sys.executable, "-m", "unittest", "discover", "learner/tests", "-t", "."]),

    Check("learner · simulate -> learn -> evaluate end to end",
          [sys.executable, "-m", "learner.cli", "evaluate"]),

    Check("macos · Swift structure + symbols",
          [sys.executable, "tools/check_macos.py"]),

    Check("macos · committed Xcode project integrity",
          [sys.executable, "tools/check_xcodeproj.py"]),

    Check("ios · Swift structure + identifier agreement",
          [sys.executable, "tools/check_ios.py"]),

    Check("android · compile Kotlin",
          [GRADLE, ":app:compileDebugKotlin", "--console=plain", "-q"],
          cwd=ROOT / "android", needs=android_toolchain,
          skip_reason="set JAVA_HOME and ANDROID_HOME to a JDK 17 and an Android SDK"),

    Check("android · unit tests (58 tests)",
          [GRADLE, ":app:testDebugUnitTest", "--console=plain", "-q"],
          cwd=ROOT / "android", needs=android_toolchain,
          skip_reason="set JAVA_HOME and ANDROID_HOME to a JDK 17 and an Android SDK"),

    # The two that genuinely cannot run off a Mac. Listed rather than omitted, so the scorecard
    # shows the shape of what is and isn't covered.
    Check("macos · xcodebuild test",
          ["xcodebuild", "-scheme", "Guardian", "test",
           "-destination", "platform=macOS"],
          cwd=ROOT / "macos", needs=lambda: have("xcodebuild"),
          skip_reason="needs Xcode (macOS only)"),

    Check("ios · xcodegen + xcodebuild",
          ["sh", "-c", "xcodegen generate && xcodebuild -scheme Lockout "
                       "-destination 'generic/platform=iOS' build"],
          cwd=ROOT / "ios",
          needs=lambda: have("xcodebuild") and have("xcodegen"),
          skip_reason="needs Xcode + xcodegen (macOS only), and the family-controls "
                      "entitlement to sign"),
]


def run(check):
    if not check.needs():
        return "SKIP", check.skip_reason or "unavailable here"
    try:
        proc = subprocess.run(check.argv, cwd=check.cwd, capture_output=True, text=True,
                              timeout=1800)
    except FileNotFoundError:
        return "SKIP", f"{check.argv[0]} not found"
    except subprocess.TimeoutExpired:
        return "FAIL", "timed out after 30 minutes"
    if proc.returncode == 0:
        return "PASS", ""
    tail = (proc.stdout + proc.stderr).strip().splitlines()
    return "FAIL", tail[-1] if tail else f"exit {proc.returncode}"


def main():
    results = []
    width = max(len(c.name) for c in CHECKS)
    for check in CHECKS:
        print(f"  … {check.name}", end="\r", flush=True)
        status, note = run(check)
        results.append((status, check.name, note))
        mark = {"PASS": "OK  ", "FAIL": "FAIL", "SKIP": "skip"}[status]
        print(f"  {mark} {check.name.ljust(width)}  {note}")

    passed = sum(1 for s, _, _ in results if s == "PASS")
    failed = sum(1 for s, _, _ in results if s == "FAIL")
    skipped = sum(1 for s, _, _ in results if s == "SKIP")

    print(f"\n{passed} passed, {failed} failed, {skipped} skipped")
    if skipped:
        print("Skipped checks are NOT passes. See the reasons above.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
