"""Guardian keep-alive watchdog — the Windows stand-in for the macOS KeepAlive LaunchAgent.

launchd could be told "relaunch this app whenever it exits"; Windows has no such per-app service
for a normal desktop program, so this tiny process does the same job: every few seconds it checks
whether Guardian is alive (via its named mutex) and starts it again if not. It holds its own mutex
so Guardian can tell whether the watchdog is running, and exits when Guardian drops the stop-flag
file — which only happens when keep-alive is switched off behind the passcode.

Started by Guardian and registered under HKCU\\...\\Run so it survives a reboot.
"""

import ctypes
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from guardian.paths import BUNDLE_ID, KEEPALIVE_LABEL  # noqa: E402

APP_MUTEX = "Global\\" + BUNDLE_ID
KEEPALIVE_MUTEX = "Global\\" + KEEPALIVE_LABEL
STOP_FLAG = HERE / ".keepalive-stop"

POLL_SECONDS = 5
SYNCHRONIZE = 0x00100000
ERROR_ALREADY_EXISTS = 183

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


def mutex_exists(name: str) -> bool:
    h = kernel32.OpenMutexW(SYNCHRONIZE, False, name)
    if h:
        kernel32.CloseHandle(h)
        return True
    return False


def pythonw() -> str:
    exe = Path(sys.executable)
    cand = exe.with_name("pythonw.exe")
    return str(cand if cand.exists() else exe)


def launch_guardian() -> None:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen([pythonw(), str(HERE / "run_guardian.pyw")],
                     creationflags=flags, close_fds=True, cwd=str(HERE))


def main() -> int:
    # One watchdog only.
    kernel32.CreateMutexW(None, True, KEEPALIVE_MUTEX)
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        return 0

    while True:
        if STOP_FLAG.exists():
            return 0
        if not mutex_exists(APP_MUTEX):
            try:
                launch_guardian()
            except Exception:
                pass
            # Give it room to come up before deciding it's dead again.
            time.sleep(10)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    sys.exit(main())
