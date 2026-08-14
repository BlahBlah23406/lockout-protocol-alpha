"""Port of `Capture/ScreenCapturer.swift`.

Grabs a single screenshot of the monitor the foreground app is on — one frame on demand, no
recording, the same contract as the Mac app's `SCScreenshotManager.captureImage`. Downscaled so
uploads stay small/fast, matching the 1280px cap.

Windows has no Screen Recording TCC prompt for a classic desktop app, so `has_permission()` answers
the question empirically instead of by asking the OS: can we actually obtain a frame right now?
Windows 11 does keep a privacy toggle for programmatic graphics capture, and that is checked too —
see `capture_consent_denied()`.
"""

import ctypes
import winreg

from PIL import Image, ImageGrab

from .. import win32

MAX_WIDTH = 1280

# Windows 11 privacy setting: Settings ▸ Privacy & security ▸ App permissions. When a capability is
# denied here, its ConsentStore value reads "Deny". Missing keys mean the OS build has no such
# toggle, which is not a denial.
_CONSENT_ROOT = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore"
_CAPTURE_CAPABILITIES = ("graphicsCaptureProgrammatic", "graphicsCaptureWithoutBorder")


def gdi_grab(bbox=None):
    try:
        user32 = win32.user32
        gdi32 = win32.gdi32
        left, top = (bbox[0], bbox[1]) if bbox else (0, 0)
        right, bottom = (bbox[2], bbox[3]) if bbox else (user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))
        w, h = max(1, right - left), max(1, bottom - top)
        hDC = user32.GetDC(0)
        mDC = gdi32.CreateCompatibleDC(hDC)
        bmp = gdi32.CreateCompatibleBitmap(hDC, w, h)
        gdi32.SelectObject(mDC, bmp)
        gdi32.BitBlt(mDC, 0, 0, w, h, hDC, left, top, 0x00CC0020)
        bmpinfo = (ctypes.c_uint32 * 11)()
        bmpinfo[0] = 40
        bmpinfo[1] = w
        bmpinfo[2] = -h
        bmpinfo[3] = 1 | (32 << 16)
        bmpinfo[4] = 0
        buf = ctypes.create_string_buffer(w * h * 4)
        gdi32.GetDIBits(mDC, bmp, 0, h, buf, bmpinfo, 0)
        user32.ReleaseDC(0, hDC)
        gdi32.DeleteDC(mDC)
        gdi32.DeleteObject(bmp)
        return Image.frombytes("RGBA", (w, h), buf.raw, "raw", "BGRA")
    except Exception:
        return None


def capture(max_width: int = MAX_WIDTH):
    """One screenshot of the monitor showing the foreground window, or None if capture failed."""
    hwnd = win32.user32.GetForegroundWindow()
    bbox = win32.monitor_rect_for_window(hwnd) if hwnd else win32.monitor_rects()[0]
    img = None
    try:
        img = ImageGrab.grab(bbox=bbox)
    except Exception:
        pass
    if img is None:
        img = gdi_grab(bbox)
    if img is None or img.width <= 0 or img.height <= 0:
        return None

    if img.width > max_width:
        scale = max_width / float(img.width)
        img = img.resize((max_width, max(1, int(img.height * scale))))
    return img


def has_permission() -> bool:
    """Can Guardian see the screen at all right now?

    Best-effort and empirical: a capture that returns a real frame is the permission. Combined with
    the Windows privacy toggle, this is the analogue of the Mac app's Screen Recording check.
    """
    if capture_consent_denied():
        return False
    try:
        bbox = win32.monitor_rects()[0]
        # A 1px-tall strip is enough to prove capture works and costs nothing.
        strip = (bbox[0], bbox[1], bbox[2], min(bbox[1] + 8, bbox[3]))
        try:
            img = ImageGrab.grab(bbox=strip)
        except Exception:
            img = gdi_grab(strip)
        return img is not None and img.width > 0 and img.height > 0
    except Exception:
        return False


def capture_consent_denied() -> bool:
    """True when a Windows privacy toggle explicitly denies programmatic screen capture."""
    for cap in _CAPTURE_CAPABILITIES:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _CONSENT_ROOT + "\\" + cap) as k:
                value, _ = winreg.QueryValueEx(k, "Value")
                if str(value).lower() == "deny":
                    return True
        except OSError:
            continue          # capability not present on this build — not a denial
    return False
