"""Package the Windows app into a folder anybody can unzip and run.

    python -m pip install pyinstaller pillow pystray pywin32
    python tools/build_windows.py

Produces `dist/LockoutProtocol/` with `LockoutProtocol.exe` in it.

Two decisions worth explaining:

**A folder, not a single file.** PyInstaller's `--onefile` unpacks itself into a temp directory on
every launch, which costs a couple of seconds of startup and — much worse for this app — makes the
executable path change between runs. The keep-alive watchdog and the login-item registration both
record where to relaunch from, so a moving path would quietly break the two features whose entire
job is surviving a restart.

**Windowed, not console.** The entry point is a `.pyw`, so there is no terminal. A console window
flashing up on every launch of a background monitor is the kind of detail that makes people
uninstall something.

The learner is bundled too. It is stdlib-only and about 40 KB, and `guardian/focus/learned.py`
imports it from the repo root when present — so shipping it means the experimental learning
feature works in a packaged build rather than silently doing nothing.
"""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WINDOWS = ROOT / "windows"
DIST = ROOT / "dist"
BUILD = ROOT / "build"

APP_NAME = "LockoutProtocol"
ENTRY = WINDOWS / "run_guardian.pyw"


def main() -> int:
    if sys.platform != "win32":
        print("This packages a Windows app; run it on Windows.")
        return 1
    if not ENTRY.exists():
        print(f"missing entry point: {ENTRY}")
        return 1

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller is not installed. python -m pip install pyinstaller")
        return 1

    # A stale build/ is the most common cause of a mystifying packaging failure.
    for path in (DIST / APP_NAME, BUILD):
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)

    argv = [
        sys.executable, "-m", "PyInstaller",
        "--name", APP_NAME,
        "--noconfirm",
        "--clean",
        # See the module docstring: not --onefile, and no console.
        "--windowed",
        "--distpath", str(DIST),
        "--workpath", str(BUILD),
        "--specpath", str(BUILD),
        # The app imports these lazily or through a package `__init__`, so PyInstaller's static
        # analysis misses them and they have to be named.
        "--hidden-import", "pystray._win32",
        "--hidden-import", "PIL._tkinter_finder",
        # tkinter's Tcl/Tk data is collected automatically, but the emulator catalogue and the
        # keep-alive watchdog are plain files the app reads at runtime.
        "--add-data", f"{WINDOWS / 'keepalive.pyw'};.",
        str(ENTRY),
    ]

    print("  ".join(argv[:6]), "…")
    result = subprocess.run(argv, cwd=ROOT)
    if result.returncode != 0:
        return result.returncode

    bundle = DIST / APP_NAME
    if not bundle.exists():
        print("PyInstaller reported success but produced no bundle")
        return 1

    # Ship the learner alongside, so the experimental learning feature isn't dead in a packaged
    # build. `learned.py` looks three directories up from itself for a `learner` package, which is
    # exactly where this puts it.
    learner_src = ROOT / "learner"
    if learner_src.exists():
        shutil.copytree(learner_src, bundle / "learner",
                        ignore=shutil.ignore_patterns("__pycache__", "data", "tests"),
                        dirs_exist_ok=True)

    for doc in ("README.md", "SAFEGUARDS.md", "LICENSE"):
        source = ROOT / doc
        if source.exists():
            shutil.copy2(source, bundle / source.name)

    size = sum(f.stat().st_size for f in bundle.rglob("*") if f.is_file())
    print(f"\nBuilt {bundle} ({size / 1_048_576:.1f} MB)")
    print(f"Run it with: {bundle / (APP_NAME + '.exe')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
