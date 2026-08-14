"""Port of `Service/LaunchAtLogin.swift` + `Service/KeepAliveAgent.swift`.

Two tiers of persistence, so quitting or killing Guardian isn't a lasting bypass:

* **Login item** — an `HKCU\\...\\CurrentVersion\\Run` value. The Windows counterpart of
  `SMAppService.mainApp`: Guardian comes back at the next sign-in.
* **Keep-alive** — a tiny watchdog process (`keepalive.pyw`) that relaunches Guardian within ~10s of
  *any* exit: Quit, force-quit from Task Manager, or crash. This is what launchd's KeepAlive agent
  did on the Mac. The watchdog is itself registered in `Run`, so it survives a reboot.

A user with admin rights can still delete the Run value, end both processes, or delete the app; like
everything in the tamper layer this raises the cost and the noise of a bypass rather than making one
impossible. When keep-alive is on it already covers login, so the plain login item is dropped to
avoid launching Guardian twice — the same reconciliation the Mac app's `Persistence` did.
"""

import ctypes
import os
import subprocess
import sys
import winreg
from pathlib import Path

from ..models.event_log import EventLog
from ..models.prefs import Prefs
from ..paths import APP_ROOT, KEEPALIVE_LABEL, BUNDLE_ID

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_VALUE = "LockoutProtocolGuardian"
KEEPALIVE_VALUE = "LockoutProtocolGuardianKeepAlive"

# Named mutexes: how the app and its watchdog know whether the other is alive.
APP_MUTEX = "Global\\" + BUNDLE_ID
KEEPALIVE_MUTEX = "Global\\" + KEEPALIVE_LABEL

SYNCHRONIZE = 0x00100000


def pythonw() -> str:
    """The windowed interpreter, so neither process shows a console."""
    exe = Path(sys.executable)
    candidate = exe.with_name("pythonw.exe")
    return str(candidate if candidate.exists() else exe)


def app_command() -> str:
    return f'"{pythonw()}" "{APP_ROOT / "run_guardian.pyw"}"'


def keepalive_command() -> str:
    return f'"{pythonw()}" "{APP_ROOT / "keepalive.pyw"}"'


def _mutex_exists(name: str) -> bool:
    h = ctypes.WinDLL("kernel32", use_last_error=True).OpenMutexW(SYNCHRONIZE, False, name)
    if h:
        ctypes.WinDLL("kernel32").CloseHandle(h)
        return True
    return False


def app_running() -> bool:
    return _mutex_exists(APP_MUTEX)


def keepalive_running() -> bool:
    return _mutex_exists(KEEPALIVE_MUTEX)


# ---- Run-key helpers -------------------------------------------------------------------

def _set_run_value(name: str, command: str) -> None:
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, name, 0, winreg.REG_SZ, command)


def _delete_run_value(name: str) -> None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, name)
    except OSError:
        pass


def _get_run_value(name: str):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            v, _ = winreg.QueryValueEx(k, name)
            return v
    except OSError:
        return None


# ---- login item -------------------------------------------------------------------------

class LaunchAtLogin:

    @staticmethod
    def apply(enabled: bool) -> None:
        try:
            if enabled:
                if _get_run_value(APP_VALUE) != app_command():
                    _set_run_value(APP_VALUE, app_command())
                    EventLog.shared().add("[lock] Guardian registered to launch at sign-in")
            else:
                if _get_run_value(APP_VALUE) is not None:
                    _delete_run_value(APP_VALUE)
        except OSError as e:
            EventLog.shared().add(f"[warn] login-item update failed: {e}")

    @staticmethod
    def is_enabled() -> bool:
        return _get_run_value(APP_VALUE) is not None


# ---- keep-alive watchdog -------------------------------------------------------------------

class KeepAliveAgent:

    @staticmethod
    def apply(enabled: bool) -> None:
        try:
            if enabled:
                if _get_run_value(KEEPALIVE_VALUE) != keepalive_command():
                    _set_run_value(KEEPALIVE_VALUE, keepalive_command())
                if not keepalive_running():
                    KeepAliveAgent._spawn()
                    EventLog.shared().add(
                        "[lock] keep-alive watchdog started - Guardian will relaunch if quit")
            else:
                _delete_run_value(KEEPALIVE_VALUE)
                if keepalive_running():
                    KeepAliveAgent._stop()
                    EventLog.shared().add("keep-alive watchdog removed")
        except OSError as e:
            EventLog.shared().add(f"[warn] keep-alive update failed: {e}")

    @staticmethod
    def _spawn() -> None:
        flags = 0
        flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
        flags |= getattr(subprocess, "DETACHED_PROCESS", 0)
        subprocess.Popen([pythonw(), str(APP_ROOT / "keepalive.pyw")],
                         creationflags=flags, close_fds=True,
                         cwd=str(APP_ROOT))

    @staticmethod
    def _stop() -> None:
        """Ask the watchdog to exit by dropping its stop-flag file; it checks this each loop."""
        try:
            (APP_ROOT / ".keepalive-stop").write_text("stop", encoding="utf-8")
        except OSError:
            pass

    @staticmethod
    def is_active() -> bool:
        return keepalive_running()


# ---- reconciliation ---------------------------------------------------------------------

def apply() -> None:
    """Keeps the two mechanisms from fighting. The watchdog already covers sign-in *and* immediate
    relaunch, so when it's on we drop the plain login item. Call at launch and on either toggle."""
    prefs = Prefs.shared()
    if prefs.keep_alive:
        # Clear a stale stop-flag before starting, or the fresh watchdog exits immediately.
        try:
            (APP_ROOT / ".keepalive-stop").unlink()
        except OSError:
            pass
        KeepAliveAgent.apply(True)
        LaunchAtLogin.apply(False)          # watchdog supersedes the plain login item
    else:
        KeepAliveAgent.apply(False)
        LaunchAtLogin.apply(prefs.relaunch_at_login)
