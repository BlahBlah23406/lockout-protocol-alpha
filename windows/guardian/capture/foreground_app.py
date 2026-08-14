"""Port of `Capture/FrontmostApp.swift`.

Knows which app is in front right now. macOS had `NSWorkspace.frontmostApplication` and identified
apps by bundle id; Windows has no bundle ids, so the stable identity of an app here is its
executable name, lower-cased — `chrome.exe`, `msedge.exe`, `hd-player.exe`. That is what the picker
lists and what `Prefs.monitored_apps` stores.

Two Windows wrinkles the Mac version didn't have:

* **UWP / Store apps** are hosted by `ApplicationFrameHost.exe`, so the foreground window's own PID
  names the host, not the app. We walk into the `Windows.UI.Core.CoreWindow` child to find the real
  process — otherwise every Store app (including Edge's PWA windows) would read as one app.
* **Elevated processes** can't be queried by a non-elevated Guardian. `identifier()` returns the
  sentinel `UNREADABLE` for those instead of pretending nothing is in front; the monitor treats it
  as a screen it cannot attribute and the tamper guard reports it.
"""

import ctypes

from .. import win32
from ..win32 import kernel32, user32

# Returned when a window is in the foreground but we are not permitted to identify its process.
UNREADABLE = "?unreadable"

# Shells that host another app's window; the real app is a child process.
_HOSTS = {"applicationframehost.exe"}


def _exe_id(path):
    if not path:
        return None
    return path.replace("/", "\\").rsplit("\\", 1)[-1].lower()


def foreground_hwnd():
    return user32.GetForegroundWindow()


def identifier():
    """Identifier of the foreground app: its lower-cased executable name, or `UNREADABLE`."""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    pid = win32.pid_of_window(hwnd)
    if not pid:
        return None

    path = win32.process_image_path(pid)
    if path is None:
        return UNREADABLE
    name = _exe_id(path)

    if name in _HOSTS:
        # Look inside the frame host for the hosted app's own process.
        for child in win32.enum_child_windows(hwnd):
            if win32.class_name(child) != "Windows.UI.Core.CoreWindow":
                continue
            cpid = win32.pid_of_window(child)
            if cpid and cpid != pid:
                cpath = win32.process_image_path(cpid)
                if cpath:
                    return _exe_id(cpath)
    return name


def title() -> str:
    """Foreground window title — used only for the activity log."""
    hwnd = user32.GetForegroundWindow()
    return win32.window_text(hwnd) if hwnd else ""


def short_name(identifier_: str) -> str:
    """Human-friendly name for logs/alerts."""
    if not identifier_:
        return "?"
    if identifier_ == UNREADABLE:
        return "an app Guardian can't identify"
    base = identifier_[:-4] if identifier_.lower().endswith(".exe") else identifier_
    return base.replace("-", " ").replace("_", " ").title()


def _pids_for(identifier_: str):
    """Every running PID whose executable matches the identifier, via the window list.

    Enumerating windows (rather than the whole process table) is deliberate: an app with no window
    isn't on screen, so it is not what we need to hide or close.
    """
    pids = set()
    for hwnd in win32.enum_windows():
        if not user32.IsWindowVisible(hwnd):
            continue
        pid = win32.pid_of_window(hwnd)
        if not pid:
            continue
        path = win32.process_image_path(pid)
        if path and _exe_id(path) == identifier_:
            pids.add(pid)
    return pids


def windows_for(identifier_: str):
    """Visible top-level windows belonging to the app."""
    out = []
    for hwnd in win32.enum_windows():
        if not user32.IsWindowVisible(hwnd):
            continue
        pid = win32.pid_of_window(hwnd)
        path = win32.process_image_path(pid) if pid else None
        if path and _exe_id(path) == identifier_:
            out.append(hwnd)
    return out


def hide(identifier_: str) -> None:
    """Minimise the app — send it out of the way, escapable. Equivalent to NSRunningApplication.hide."""
    for hwnd in windows_for(identifier_):
        user32.ShowWindow(hwnd, win32.SW_MINIMIZE)


def quit(identifier_: str) -> None:
    """Close the offending app: ask politely (WM_CLOSE), then terminate what's left.

    The Mac app called `NSRunningApplication.terminate()`, which posts a quit event and lets the app
    tidy up. WM_CLOSE is the same courtesy on Windows; the TerminateProcess follow-up covers windows
    that ignore it (a modal "save your work?" dialog would otherwise defeat the block).
    """
    pids = _pids_for(identifier_)
    for hwnd in windows_for(identifier_):
        user32.PostMessageW(hwnd, win32.WM_CLOSE, 0, 0)

    import time
    time.sleep(1.2)

    for pid in pids:
        # Still alive after being asked to close? Force it.
        if not _pid_alive(pid):
            continue
        h = kernel32.OpenProcess(win32.PROCESS_TERMINATE, False, pid)
        if h:
            try:
                kernel32.TerminateProcess(h, 0)
            finally:
                kernel32.CloseHandle(h)


def _pid_alive(pid: int) -> bool:
    h = kernel32.OpenProcess(win32.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return False
    try:
        code = ctypes.c_ulong()
        if kernel32.GetExitCodeProcess(h, ctypes.byref(code)):
            return code.value == 259          # STILL_ACTIVE
        return True
    finally:
        kernel32.CloseHandle(h)
