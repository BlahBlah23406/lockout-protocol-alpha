"""Where Guardian keeps its state on Windows.

The macOS app used UserDefaults (a per-app plist) plus the Keychain. The Windows analogues are a
JSON file and a DPAPI-encrypted blob, both under the user's LocalAppData — per-user, not roaming,
so secrets never travel to another machine.
"""

import os
from pathlib import Path

APP_VENDOR = "LockoutProtocol"
APP_NAME = "Guardian"

# Same reverse-DNS identity the macOS app uses for its Keychain service / launch agent label.
BUNDLE_ID = "com.lockoutprotocol.guardian"
KEEPALIVE_LABEL = "com.lockoutprotocol.guardian.keepalive"


def data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    d = Path(base) / APP_VENDOR / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


PREFS_FILE = data_dir() / "prefs.json"
SECRETS_FILE = data_dir() / "secrets.dat"
LOG_FILE = data_dir() / "activity.log"
HEARTBEAT_FILE = data_dir() / "heartbeat"

# Repo root of the Windows app (…/windows), used to locate the keep-alive watchdog script.
APP_ROOT = Path(__file__).resolve().parent.parent
