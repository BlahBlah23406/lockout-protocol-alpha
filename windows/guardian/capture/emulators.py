"""Port of `Capture/Emulators.swift`.

Emulators, simulators, virtual machines and phone-mirroring apps — every way this PC can put
ANOTHER device's screen inside a window here.

These are a monitoring blind spot by nature: to Guardian an emulator is just one more Windows app,
but what's inside its window is a whole other device with its own browser and its own app store,
none of which this PC's other content blockers touch. So every one of them belongs on the monitored
list. (The screenshot is of the whole monitor, so an emulator's window is captured and classified
exactly like any other app's — no special capture path is needed.)

`sync_monitored_apps()` folds the installed ones into `Prefs.monitored_apps` at every launch, so an
emulator installed tomorrow is watched the first time it runs, not whenever the list is next edited
by hand.

The families are the Mac catalog's, re-keyed to the Windows executables that provide them.
Remote-desktop / cloud-streaming clients are deliberately still absent: they show a machine that is
somewhere else, which is a different question from a device emulated on this PC. Phone Link IS here
— it puts a real phone's screen on this display, the same blind spot as iPhone Mirroring on the Mac.
"""

import os
import threading
from pathlib import Path

# Known executables, by family. Listed whether or not they're installed today — the catalog is what
# makes a future install get picked up automatically.
CATALOG = {
    # ── Mobile-device emulators
    "hd-player.exe",            # BlueStacks 5 player
    "bluestacks.exe",
    "hd-multiinstancemanager.exe",
    "bstkvm.exe",
    "nox.exe",                  # NoxPlayer
    "noxvmhandle.exe",
    "memu.exe",                 # MEmu
    "memuheadless.exe",
    "dnplayer.exe",             # LDPlayer
    "ldboxheadless.exe",
    "player.exe",               # Genymotion player
    "genymotion.exe",
    "emulator.exe",             # Android SDK / Android Studio AVD
    "qemu-system-x86_64.exe",
    "qemu-system-aarch64.exe",
    "qemu-system-i386.exe",
    "studio64.exe",             # Android Studio — hosts the AVD window
    "wsaclient.exe",            # Windows Subsystem for Android
    "yourphone.exe",            # Phone Link — a real phone's screen, on this PC
    "phonelink.exe",

    # ── Virtual machines (a guest OS is a guest browser)
    "virtualboxvm.exe",
    "virtualbox.exe",
    "vmware.exe",
    "vmplayer.exe",
    "vmware-vmx.exe",
    "vmconnect.exe",            # Hyper-V VM Connection
    "windowssandboxclient.exe",
    "windowssandbox.exe",
    "utm.exe",
    "qemu-system-arm.exe",

    # ── Compatibility layers (another platform's app inside a window here)
    "wine.exe",
    "crossover.exe",

    # ── Console emulators (still a second screen, with a browser in some cases)
    "dolphin.exe",
    "citra-qt.exe",
    "ppsspp.exe",
    "ppssppwindows.exe",
    "pcsx2.exe",
    "pcsx2-qt.exe",
    "rpcs3.exe",
    "retroarch.exe",
    "ryujinx.exe",
    "yuzu.exe",
    "cemu.exe",
}

_lock = threading.RLock()

# Places an emulator binary lives without ever registering itself as an installed app — the Windows
# counterpart of the Mac scan for `~/Library/Android/sdk/emulator`.
def _search_dirs():
    home = Path.home()
    localappdata = os.environ.get("LOCALAPPDATA", str(home / "AppData" / "Local"))
    dirs = [
        Path(localappdata) / "Android" / "Sdk" / "emulator",
        Path(localappdata) / "Android" / "Sdk" / "emulator" / "qemu" / "windows-x86_64",
        home / "AppData" / "Local" / "Android" / "Sdk" / "emulator",
    ]
    sdk = os.environ.get("ANDROID_SDK_ROOT") or os.environ.get("ANDROID_HOME")
    if sdk:
        dirs.append(Path(sdk) / "emulator")
    for pf in ("ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(pf)
        if base:
            dirs.append(Path(base) / "qemu")
    return dirs


def installed_process_ids() -> set:
    """Emulator binaries present on disk but not registered anywhere Windows would list them."""
    found = set()
    for d in _search_dirs():
        try:
            if not d.is_dir():
                continue
        except OSError:
            continue
        for exe in CATALOG:
            try:
                if (d / exe).is_file():
                    found.add(exe)
            except OSError:
                continue
    return found


def installed_ids() -> set:
    """The subset of the catalog actually present on this PC right now."""
    from . import installed_apps
    found = set()
    try:
        found |= {a.id for a in installed_apps.all()} & CATALOG
    except Exception:
        pass
    found |= installed_process_ids()
    return found


def all_ids() -> set:
    return set(CATALOG)


def is_emulator(identifier: str) -> bool:
    """Is this app one of the emulated-device family? Tags it in the picker so unticking one is at
    least a deliberate, informed act."""
    return identifier in CATALOG


def sync_monitored_apps(prefs=None) -> set:
    """Add every installed emulated device to the monitored list. Runs at launch, so a newly
    installed emulator is covered without anyone remembering to tick a box. Returns what it added.

    This intentionally re-adds an emulator that was unticked in Settings — on an accountability app,
    "I quietly removed the Android emulator from the watch list" is exactly the edit that shouldn't
    stick silently. The additions are written to the activity log either way.
    """
    from ..models.event_log import EventLog
    from ..models.prefs import Prefs
    from . import installed_apps

    prefs = prefs or Prefs.shared()
    with _lock:
        installed = installed_ids()
        added = installed - prefs.monitored_apps
        if not added:
            return set()
        prefs.monitored_apps = prefs.monitored_apps | added
        names = ", ".join(sorted(installed_apps.name(i) for i in added))
        EventLog.shared().add(f"[emu] emulated devices added to the watch list: {names}")
        return added
