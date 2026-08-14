"""Port of `Capture/InstalledApps.swift`.

Enumerates installed applications so the picker can offer any app, not just the running ones. macOS
had one convention (`*.app` bundles in a handful of directories); Windows has several, so we union
the reliable ones:

1. **`App Paths`** in both registry hives — the canonical "this executable is installed" list, and
   where browsers, chat clients and the like register themselves.
2. **Uninstall entries** — `DisplayIcon` usually points straight at the main executable.
3. **Start Menu shortcuts** — resolved with the Windows Script Host, which is the only accurate way
   to read a `.lnk` target without pulling in a COM binding.
4. **Running windowed processes** — anything on screen right now is monitorable whether or not it
   installed itself anywhere.
5. **Bundle-less emulators found on disk** (see `emulators.py`), for the same reason the Mac app
   scanned for the Android SDK emulator: an emulated device is the blind spot that matters most.

Apps are keyed by lower-cased executable name, matching `foreground_app.identifier()`.
"""

import json
import os
import subprocess
import threading
import winreg
from pathlib import Path

from .. import win32
from ..paths import data_dir

CACHE_FILE = data_dir() / "apps_cache.json"

_lock = threading.RLock()
_cache = None

# Windows components that are never a thing a person "uses", so listing them is only noise.
_SKIP = {
    "regsvr32.exe", "rundll32.exe", "dllhost.exe", "svchost.exe", "conhost.exe",
    "sihost.exe", "ctfmon.exe", "fontdrvhost.exe", "dwm.exe", "csrss.exe",
    "wininit.exe", "winlogon.exe", "services.exe", "lsass.exe", "smss.exe",
    "searchhost.exe", "startmenuexperiencehost.exe", "shellexperiencehost.exe",
    "runtimebroker.exe", "textinputhost.exe", "applicationframehost.exe",
    "systemsettingsbroker.exe", "backgroundtaskhost.exe", "unsecapp.exe",
    "wmiprvse.exe", "audiodg.exe", "spoolsv.exe", "taskhostw.exe", "explorer.exe",
}


class App:
    __slots__ = ("id", "name", "path")

    def __init__(self, id, name, path):
        self.id = id
        self.name = name
        self.path = path

    def as_dict(self):
        return {"id": self.id, "name": self.name, "path": self.path}


def _pretty(exe: str) -> str:
    base = exe[:-4] if exe.lower().endswith(".exe") else exe
    return base.replace("-", " ").replace("_", " ").title()


def _add(found: dict, path: str, name: str = None) -> None:
    if not path:
        return
    path = path.strip().strip('"')
    if not path.lower().endswith(".exe"):
        return
    exe = path.replace("/", "\\").rsplit("\\", 1)[-1].lower()
    if exe in _SKIP:
        return
    if exe in found and found[exe].name:
        return
    found[exe] = App(exe, name or _pretty(exe), path)


def _scan_app_paths(found: dict) -> None:
    sub = r"Software\Microsoft\Windows\CurrentVersion\App Paths"
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(hive, sub) as root:
                i = 0
                while True:
                    try:
                        name = winreg.EnumKey(root, i)
                    except OSError:
                        break
                    i += 1
                    try:
                        with winreg.OpenKey(root, name) as k:
                            path, _ = winreg.QueryValueEx(k, "")
                        _add(found, path)
                    except OSError:
                        continue
        except OSError:
            continue


def _scan_uninstall(found: dict) -> None:
    subs = [
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE,
         r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    for hive, sub in subs:
        try:
            with winreg.OpenKey(hive, sub) as root:
                i = 0
                while True:
                    try:
                        key = winreg.EnumKey(root, i)
                    except OSError:
                        break
                    i += 1
                    try:
                        with winreg.OpenKey(root, key) as k:
                            display = _try_value(k, "DisplayName")
                            icon = _try_value(k, "DisplayIcon")
                    except OSError:
                        continue
                    if not icon:
                        continue
                    icon = icon.split(",")[0]
                    _add(found, icon, display)
        except OSError:
            continue


def _try_value(key, name):
    try:
        v, _ = winreg.QueryValueEx(key, name)
        return v if isinstance(v, str) else None
    except OSError:
        return None


def _start_menu_dirs():
    dirs = []
    for var in ("ProgramData", "APPDATA"):
        base = os.environ.get(var)
        if base:
            dirs.append(Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
    return [d for d in dirs if d.is_dir()]


def _scan_start_menu(found: dict) -> None:
    """Resolve every Start Menu .lnk to its target with one Windows Script Host call."""
    dirs = _start_menu_dirs()
    if not dirs:
        return
    joined = ",".join(f"'{str(d)}'" for d in dirs)
    script = (
        "$ws = New-Object -ComObject WScript.Shell; "
        f"Get-ChildItem -Path {joined} -Filter *.lnk -Recurse -ErrorAction SilentlyContinue | "
        "ForEach-Object { try { $t = $ws.CreateShortcut($_.FullName).TargetPath; "
        "if ($t -and $t.ToLower().EndsWith('.exe')) "
        "{ Write-Output ($_.BaseName + '|' + $t) } } catch {} }"
    )
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        return
    for line in (out.stdout or "").splitlines():
        if "|" not in line:
            continue
        name, path = line.split("|", 1)
        _add(found, path.strip(), name.strip())


def _scan_running(found: dict) -> None:
    seen = set()
    for hwnd in win32.enum_windows():
        if not win32.user32.IsWindowVisible(hwnd):
            continue
        pid = win32.pid_of_window(hwnd)
        if not pid or pid in seen:
            continue
        seen.add(pid)
        path = win32.process_image_path(pid)
        if path:
            _add(found, path)


def all(refresh: bool = False):
    """Every discoverable app, sorted by display name. Cached — the scan touches the registry."""
    global _cache
    with _lock:
        if not refresh and _cache is not None:
            return _cache
        if not refresh:
            cached = _load_cache()
            if cached is not None:
                _cache = cached
                return _cache

        found: dict = {}
        _scan_app_paths(found)
        _scan_uninstall(found)
        _scan_start_menu(found)
        _scan_running(found)

        from . import emulators
        for exe in emulators.installed_ids():
            if exe not in found:
                found[exe] = App(exe, _pretty(exe), "")

        _cache = sorted(found.values(), key=lambda a: a.name.lower())
        _save_cache(_cache)
        return _cache


def _load_cache():
    try:
        raw = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        return [App(a["id"], a["name"], a.get("path", "")) for a in raw]
    except Exception:
        return None


def _save_cache(apps):
    try:
        CACHE_FILE.write_text(json.dumps([a.as_dict() for a in apps]), encoding="utf-8")
    except Exception:
        pass


def name(for_id: str) -> str:
    """Best-effort display name for an identifier."""
    for app in all():
        if app.id == for_id:
            return app.name
    from . import foreground_app
    return foreground_app.short_name(for_id)
