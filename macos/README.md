# Guardian for macOS

The macOS half of [Lockout Protocol](../README.md). You declare a task, it screenshots whichever
watched app is frontmost, asks a model you chose whether that screen is part of that task, and
raises a full-screen block when it clearly isn't. Start and stop it from the menu-bar item.

The original content-rules mode is still here, opt-in and off by default, under Settings.

> ⚠️ Run this only on a Mac **you own**, or where the person using it has knowingly agreed.

> **Status: builds and tests clean** on Xcode 16.4, via the `macos` job in
> `.github/workflows/build.yml`, which runs `xcodebuild test` on every push. What has NOT happened
> is anyone running it on a real Mac and watching it block something — the tests cover the logic,
> not the ScreenCaptureKit path or the menu-bar UI.

## Requirements

**Xcode 16 or newer.** `Guardian.xcodeproj` is objectVersion 77; Xcode 15.4 refuses to open it with
*"a future Xcode project file format"*. If you would rather not upgrade, regenerate the project from
the spec instead — it is the source of truth anyway:

```sh
brew install xcodegen
cd macos && xcodegen generate
```

New Swift files are picked up automatically by `xcodegen` (the spec globs directories), but the
committed `.xcodeproj` lists files explicitly, so if you add one by hand it must be added there too.

## How it works

```
NSWorkspace.frontmostApplication ──► which app is frontmost?

MonitorService (response-driven loop):
   while a MONITORED app is frontmost:
     ├─► ScreenCapturer (SCScreenshotManager) → one screenshot, no recording
     ├─► FrameQuality → blank/protected? → "can't see" (alert, never a hard block)
     ├─► OllamaClient  → POST /api/chat to Ollama Cloud → {violation, reason}
     └─► if violation → BlockController (full-screen block on every display)
                      + Pusher (ntfy) + local notification
```

Platform mapping against the Android app:

| Android | macOS |
|---|---|
| AccessibilityService foreground tracking | `NSWorkspace.frontmostApplication` |
| `AccessibilityService.takeScreenshot()` | `SCScreenshotManager.captureImage` (ScreenCaptureKit) |
| EncryptedSharedPreferences | `UserDefaults` + macOS **Keychain** for secrets |
| Sticky `BlockActivity` | `BlockController` window per display, above the menu bar |
| ntfy push (`Pusher`) | identical ntfy push |

## Build & run

Requires **macOS 14+**, **Xcode 15+**, and [XcodeGen](https://github.com/yonaskolb/XcodeGen).

```bash
brew install xcodegen
```

```bash
cd macos && xcodegen generate && open Guardian.xcodeproj
```

Then ⌘R. From the command line instead:

```bash
xcodebuild -project Guardian.xcodeproj -scheme Guardian -destination 'platform=macOS' build
```

```bash
xcodebuild -project Guardian.xcodeproj -scheme Guardian -destination 'platform=macOS' test
```

The app is ad-hoc signed. Because a local rebuild changes the signature, macOS re-prompts for
Keychain access and **resets the Screen Recording grant** each time you rebuild — approve both
again. Build once, use it; a real Developer ID signature makes this one-time.

## First run

1. **Grant Screen Recording.** The first capture triggers the prompt — approve Guardian in *System
   Settings ▸ Privacy & Security ▸ Screen Recording*, then relaunch. Until then every screen reads
   as "can't see".
2. **Settings ▸ AI** — paste your Ollama Cloud API key (kept in the Keychain). The optional backup
   key is used when the first hits its quota, and Guardian switches back when that one runs out. If
   both are exhausted the check is logged as "AI busy" and skipped — never a block.
3. **Settings ▸ Alerts** — subscribe to the private `guardian-…` code in the ntfy app and press
   **Send test alert**.
4. **Apps** — pick what to monitor. Emulators, simulators and iPhone Mirroring are folded in
   automatically (`Capture/Emulators.swift`), since a guest device is a blind spot otherwise.
5. **Guidelines** — edit what counts as a violation.
6. **Passcode** — set one. It gates opening Guardian, dismissing a block, and Stop/Quit in the menu
   bar.
7. Leave it in **TEST MODE** for a day, read the log, then arm it.

## Behaviour worth knowing

- **Block screen.** Covers every display above the menu bar. **Dismiss** needs no passcode but
  **quits the offending app**; **Override** keeps the app and needs the passcode (5-minute grace).
  ⌘Q still quits Guardian, so a forgotten passcode can never lock you out of your Mac.
- **Menu bar + background.** Closing the window drops the Dock icon and keeps monitoring. Reopen
  from the 👁 menu-bar item.
- **Keep-alive.** On by default: a bundled launchd agent relaunches Guardian within ~10s of any
  quit, force-quit or crash, and quitting pushes your partner. Turn it off in *Settings ▸ Tamper
  resistance* (behind the passcode) before quitting for a legitimate reason.
- **Screen off / locked.** Monitoring pauses while the display is asleep or the session is locked,
  and says so in the log — a dark screen is not a "can't see" alert.

## Layout

```
Guardian/
  GuardianApp.swift   @main: WindowGroup + MenuBarExtra + Dock-hide-on-close
  Models/    Prefs, Keychain, EventLog
  AI/        OllamaClient (prompt + verdict), FrameQuality
  Capture/   ScreenCapturer, FrontmostApp, InstalledApps, Emulators, ScreenState
  Push/      Pusher (ntfy)
  Service/   MonitorService, BlockController, Overrides, TamperGuard, SettingsGuard,
             KeepAliveAgent, LaunchAtLogin, SafetyCovenant
  UI/        ContentView, SettingsView, GuidelinesView, AppPickerView, BlockView,
             PledgeView, PasscodeEditor, MenuBarView, Theme (LCARS)
GuardianTests/         pure-logic unit tests
tools/make_icon.swift  regenerates the app icon
project.yml            XcodeGen spec — new files need `xcodegen generate` before building
```

## Known limits

- Guardian screenshots the **whole display** while a monitored app is frontmost (macOS has no
  per-app equivalent of the Android capture) — same effective result: it sees what you see.
- Screen Recording is a TCC grant; it must be given by hand and cannot be self-granted.
- An admin can `launchctl bootout` the keep-alive agent or delete the app. This raises the cost and
  the noise of a bypass; it does not make one impossible. See [SAFEGUARDS.md](../SAFEGUARDS.md).
