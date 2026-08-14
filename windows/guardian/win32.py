"""Thin ctypes bindings for the Win32 calls Guardian needs.

Kept in one place so the rest of the app reads like the Swift original instead of like ctypes.
Nothing here needs pywin32; everything is in the OS.
"""

import ctypes
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)

# ---- constants ---------------------------------------------------------------------------

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_TERMINATE = 0x0001
SW_MINIMIZE = 6
SW_SHOWMINNOACTIVE = 7
SW_RESTORE = 9
WM_CLOSE = 0x0010
SPI_GETSCREENSAVERRUNNING = 0x0072
DESKTOP_SWITCHDESKTOP = 0x0100
MONITOR_DEFAULTTOPRIMARY = 0x0001
ERROR_ALREADY_EXISTS = 183

# Per-monitor-v2 DPI awareness, so window/monitor rects are in real pixels and screenshots line up.
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)

# ---- prototypes --------------------------------------------------------------------------

user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
user32.OpenInputDesktop.restype = wintypes.HANDLE
user32.CloseDesktop.argtypes = [wintypes.HANDLE]
user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.MonitorFromWindow.restype = wintypes.HANDLE

kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
user32.EnumChildWindows.argtypes = [wintypes.HWND, WNDENUMPROC, wintypes.LPARAM]


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", RECT),
                ("rcWork", RECT), ("dwFlags", wintypes.DWORD)]


MONITORENUMPROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL, wintypes.HANDLE, wintypes.HDC, ctypes.POINTER(RECT), wintypes.LPARAM)
user32.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.POINTER(RECT),
                                       MONITORENUMPROC, wintypes.LPARAM]
user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]


# ---- helpers -----------------------------------------------------------------------------

def set_dpi_aware() -> None:
    """Opt into per-monitor DPI awareness so captures and overlay geometry are in real pixels."""
    try:
        user32.SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
    except Exception:
        try:
            ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)   # PROCESS_PER_MONITOR_DPI_AWARE
        except Exception:
            try:
                user32.SetProcessDPIAware()
            except Exception:
                pass


def window_text(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def class_name(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def pid_of_window(hwnd) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def process_image_path(pid: int):
    """Full path of a process's executable, or None if we're not allowed to look.

    Returning None matters: on Windows a non-elevated Guardian cannot query an elevated process,
    and that is a genuine monitoring blind spot the tamper guard reports rather than ignores.
    """
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None
    try:
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value
        return None
    finally:
        kernel32.CloseHandle(h)


def enum_windows():
    """Every top-level window handle."""
    out = []

    @WNDENUMPROC
    def cb(hwnd, _):
        out.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    return out


def enum_child_windows(parent):
    out = []

    @WNDENUMPROC
    def cb(hwnd, _):
        out.append(hwnd)
        return True

    user32.EnumChildWindows(parent, cb, 0)
    return out


def monitor_rects():
    """(left, top, right, bottom) of every physical monitor."""
    rects = []

    @MONITORENUMPROC
    def cb(hmon, hdc, lprc, lparam):
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            r = info.rcMonitor
            rects.append((r.left, r.top, r.right, r.bottom))
        return True

    user32.EnumDisplayMonitors(None, None, cb, 0)
    return rects or [(0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))]


def monitor_rect_for_window(hwnd):
    """The monitor rect the given window sits on (primary if unknown)."""
    hmon = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTOPRIMARY)
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    if hmon and user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
        r = info.rcMonitor
        return (r.left, r.top, r.right, r.bottom)
    return monitor_rects()[0]


def workstation_locked() -> bool:
    """True when the session is locked or on a different (secure) desktop.

    `OpenInputDesktop` fails when the interactive desktop is the secure/locked one — the standard
    Win32 way to answer "is anyone able to look at this screen", and the analogue of the Mac app's
    CGSession lock check.
    """
    h = user32.OpenInputDesktop(0, False, DESKTOP_SWITCHDESKTOP)
    if h:
        user32.CloseDesktop(h)
        return False
    return True


def screensaver_running() -> bool:
    running = wintypes.BOOL()
    if user32.SystemParametersInfoW(SPI_GETSCREENSAVERRUNNING, 0, ctypes.byref(running), 0):
        return bool(running.value)
    return False


def single_instance_mutex(name: str):
    """Create a named mutex; returns (handle, already_running)."""
    h = kernel32.CreateMutexW(None, True, name)
    return h, kernel32.GetLastError() == ERROR_ALREADY_EXISTS
