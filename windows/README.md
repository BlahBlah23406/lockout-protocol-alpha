# Guardian for Windows

The Windows version of [Lockout Protocol](../README.md). Screenshots the apps/windows you choose, asks an Ollama Cloud vision model whether the screen breaks your rules, and on a violation raises a full-screen block overlay and pushes your accountability partner via ntfy.

---

## How it works

```
foreground_app.identifier() ──► which app is in front? (e.g. "chrome.exe")

MonitorService (response-driven loop):
   while a MONITORED app is in front:
     ├─► ScreenCapturer → one screenshot (Win32 GDI / ImageGrab)
     ├─► FrameQuality   → blank/protected? → "can't see" (alert, never a hard block)
     ├─► OllamaClient   → POST /api/chat to Ollama Cloud → {violation, reason}
     └─► if violation   → BlockController (full-screen block on every monitor)
                        + Pusher (ntfy) + local notification
```

### Platform mapping against macOS and Android

| macOS | Windows |
|---|---|
| `NSWorkspace.frontmostApplication` | `foreground_app.identifier()` (Win32 `GetForegroundWindow`) |
| `SCScreenshotManager.captureImage` | `screen_capturer.capture()` (GDI BitBlt / ImageGrab) |
| macOS Keychain | DPAPI encrypted store (`secrets_store.py` via `CryptProtectData`) |
| UserDefaults | `prefs.json` (`prefs.py`) |
| `BlockController` (NSWindow per display) | `BlockController` (Tk Toplevel per monitor, always-on-top) |
| ntfy push (`Pusher`) | identical ntfy push (`pusher.py`) |
| KeepAlive LaunchAgent | KeepAlive watchdog (`keepalive.pyw`) |
| System Settings pledge | Windows Settings / Control Panel pledge (`settings_guard.py`) |

---

## How to run

### Prerequisites

- **Windows 10 / 11**
- **Python 3.10+** (with `Pillow`, `pystray`, `requests` installed)

### Launching

```powershell
python windows/run_guardian.pyw
```

Or run without console window:

```powershell
pythonw windows/run_guardian.pyw
```

### Unit Tests

```powershell
python -m unittest discover -s windows/tests
```

---

## Architecture & Layout

```
windows/
  run_guardian.pyw     @main: Entry point, system tray icon (pystray), lifecycle, single-instance
  keepalive.pyw        Keep-alive watchdog (relaunches Guardian within ~10s of exit)
  guardian/
    models/            prefs.py, secrets_store.py (DPAPI), event_log.py
    ai/                ollama_client.py (prompt + verdict), frame_quality.py
    capture/           screen_capturer.py, foreground_app.py, installed_apps.py, emulators.py, screen_state.py
    push/              pusher.py (ntfy)
    service/           monitor_service.py, block_controller.py, overrides.py, tamper_guard.py,
                       tamper_alert.py, settings_guard.py, persistence.py, safety_covenant.py
    ui/                main_window.py, dashboard_view.py, settings_view.py, guidelines_view.py,
                       app_picker_view.py, block_view.py, pledge_view.py, passcode_editor.py,
                       passcode_prompt.py, theme.py (LCARS), tkroot.py
  tests/               unit and integration test suite
```
