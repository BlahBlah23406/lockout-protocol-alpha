"""Port of `Capture/ScreenState.swift`.

Can anyone actually SEE the screen right now?

This exists because a sleeping/locked PC is not a monitoring blind spot — it's a screen with
nothing on it. A capture in that state hands back a black frame, which would otherwise read as
"Guardian can't see the screen" and fire an alert every single time the display went off. Nothing
prohibited can be viewed on a dark or locked display, so pausing is correct here — unlike
capture-protected windows, which stay a real blind spot and must keep alerting. See SAFEGUARDS.md.

Windows equivalents of the three macOS checks:

| macOS                              | Windows                                              |
|------------------------------------|------------------------------------------------------|
| `CGDisplayIsAsleep`                | `RegisterPowerSettingNotification(GUID_CONSOLE_DISPLAY_STATE)` |
| `CGSessionCopyCurrentDictionary`   | `OpenInputDesktop` fails while locked / on the secure desktop  |
| screen-saver process running       | `SystemParametersInfo(SPI_GETSCREENSAVERRUNNING)`     |
"""

import ctypes
import threading
from ctypes import wintypes

from .. import win32
from ..win32 import user32

WM_POWERBROADCAST = 0x0218
PBT_POWERSETTINGCHANGE = 0x8013
DEVICE_NOTIFY_WINDOW_HANDLE = 0x00000000

# GUID_CONSOLE_DISPLAY_STATE {6FE69556-704A-47A0-8F24-C28D936FDA47}
# Data: 0 = display off, 1 = on, 2 = dimmed.


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


class POWERBROADCAST_SETTING(ctypes.Structure):
    _fields_ = [("PowerSetting", GUID), ("DataLength", wintypes.DWORD),
                ("Data", ctypes.c_ubyte * 1)]


GUID_CONSOLE_DISPLAY_STATE = GUID(
    0x6FE69556, 0x704A, 0x47A0, (ctypes.c_ubyte * 8)(0x8F, 0x24, 0xC2, 0x8D, 0x93, 0x6F, 0xDA, 0x47))

# Assume the display is on until Windows tells us otherwise; a missed notification must never make
# Guardian believe the screen is off (that would silently pause monitoring).
_display_on = True
_started = False
_lock = threading.Lock()


class _WNDCLASS(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT),
                ("lpfnWndProc", ctypes.WINFUNCTYPE(
                    ctypes.c_long, wintypes.HWND, wintypes.UINT,
                    wintypes.WPARAM, wintypes.LPARAM)),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]


WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_long, wintypes.HWND, wintypes.UINT,
                             wintypes.WPARAM, wintypes.LPARAM)


def _wnd_proc(hwnd, msg, wparam, lparam):
    global _display_on
    if msg == WM_POWERBROADCAST and wparam == PBT_POWERSETTINGCHANGE:
        setting = ctypes.cast(lparam, ctypes.POINTER(POWERBROADCAST_SETTING)).contents
        if setting.DataLength >= 1:
            _display_on = setting.Data[0] != 0
        return 1
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


_proc_ref = WNDPROC(_wnd_proc)


def _pump():
    """Message-only window that receives display-power notifications."""
    cls = _WNDCLASS()
    cls.lpfnWndProc = _proc_ref
    cls.lpszClassName = "GuardianPowerWatcher"
    cls.hInstance = win32.kernel32.GetModuleHandleW(None)
    if not user32.RegisterClassW(ctypes.byref(cls)):
        return

    HWND_MESSAGE = wintypes.HWND(-3)
    hwnd = user32.CreateWindowExW(0, "GuardianPowerWatcher", "guardian-power", 0,
                                  0, 0, 0, 0, HWND_MESSAGE, None, cls.hInstance, None)
    if not hwnd:
        return
    user32.RegisterPowerSettingNotification(
        hwnd, ctypes.byref(GUID_CONSOLE_DISPLAY_STATE), DEVICE_NOTIFY_WINDOW_HANDLE)

    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))


def start() -> None:
    """Begin listening for display on/off. Safe to call more than once."""
    global _started
    with _lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_pump, name="guardian-power", daemon=True).start()


def display_asleep() -> bool:
    return not _display_on


def locked() -> bool:
    return win32.workstation_locked()


def screensaver_running() -> bool:
    return win32.screensaver_running()


def is_visible() -> bool:
    """True when there is a lit, unlocked screen a person could be looking at."""
    return not display_asleep() and not locked() and not screensaver_running()


def reason() -> str:
    """Short description of why the screen isn't visible, for the activity log."""
    if display_asleep():
        return "asleep"
    if locked():
        return "locked"
    if screensaver_running():
        return "showing the screen saver"
    return "visible"
