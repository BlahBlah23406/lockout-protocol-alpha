# Guardian for Android

The Android half of [Lockout Protocol](../README.md). Screenshots the apps you choose, asks an
Ollama Cloud vision model whether the screen breaks your rules, and on a violation raises a sticky
block screen and pushes your accountability partner.

> ⚠️ Install this only on a phone **you own**, or where the person using it has knowingly agreed.
> Covertly monitoring someone else's phone is illegal in many places.

## How it works

```
AppWatchAccessibilityService ──► which app is really in front?
        │                        (screenshots too — no MediaProjection, no recording indicator)
MonitorService (foreground service, response-driven loop):
        ├─► takeScreenshot()   → one frame
        ├─► FrameQuality       → blank/incognito? → "can't see" (alert, never a hard block)
        ├─► OllamaClient       → POST /api/chat → {violation, category, reason}
        └─► if violation:
              ├─ BlockActivity + BlockGate (sticky: it comes back until you answer it)
              ├─ AlertPolicy   → push your partner for deliberate flags
              └─ EventLog      → every check, on-device

Tamper resistance:
  SettingsGuard         pledge screen on Settings; bounce out of Guardian's own disable pages
  GuardianAdminReceiver device-admin removal → alert
  BootReceiver          restart monitoring after reboot
  HeartbeatWorker (15m) restart the service if it died; optional ping to a watchdog server
  SafetyCovenant        alerts if the rules are gutted or the app is disarmed
```

## Build & install

Needs **JDK 17**, the **Android SDK** (platform 34), and a device on **Android 14+** (minSdk 34).

Gradle needs to know where your SDK is. Android Studio writes `local.properties` for you; from the
CLI, create it yourself:

```bash
echo "sdk.dir=$HOME/Library/Android/sdk" > android/local.properties
```

Build the APK:

```bash
cd android && ./gradlew :app:assembleDebug
```

Install it on a connected device:

```bash
adb install -r android/app/build/outputs/apk/debug/app-debug.apk
```

Run the unit tests:

```bash
cd android && ./gradlew :app:testDebugUnitTest
```

## First run

Open the app, then **Setup · permissions** and grant, in order:

1. **Accessibility** — how Guardian sees which app is in front *and* takes screenshots. Without it,
   nothing works.
2. **Display over other apps** — for the block screen.
3. **Device admin** — makes uninstalling take an extra step, and alerts your partner when admin is
   removed.
4. **Ignore battery optimisation** — keeps the service alive.

Then, from the dashboard:

- **Change passcode** — set one. It gates the whole app.
- **🔔 Set up alerts** — shows your private ntfy code; have your partner subscribe, then send a test.
- **AI · advanced settings** — paste your Ollama Cloud API key. The optional second key takes over
  when the first hits its quota (and back again when that one runs out); if both are out, the check
  is logged as "AI busy" and skipped, never a block.
- **Select apps to monitor** — browsers, socials, image apps, app stores. Newly installed apps are
  auto-enrolled from here on, so a fresh browser isn't a free pass.
- **Edit guidelines** — what counts as a violation, in plain English.
- **Test block screen (drill)** — see what a block looks like without waiting for one.

Monitoring is always on once accessibility is granted; there is no start/stop button. It starts in
**TEST MODE** — verdicts are logged and toasted but nothing is blocked. Watch *Open full log* for a
day, tune the guidelines, then uncheck **TEST MODE** in Settings to arm it.

## Behaviour worth knowing

- **The block screen is sticky.** A watchdog re-raises it whenever it isn't the top screen, so a
  swipe-up doesn't clear it. **Dismiss** (never passcode-gated, so you can't be locked out) closes
  the offending app; **Override** keeps it, behind the passcode. If a block is simply waited out for
  five minutes, it stands down *and* pushes your partner that it went unanswered.
- **Alerts are for deliberate flags.** Tampering, a search for it, a site for it, and explicit
  content always notify. Mild/incidental "suggestive" flags block and log quietly unless you opt in
  (`AlertPolicy` — deliberately not fully user-configurable, see [SAFEGUARDS.md](../SAFEGUARDS.md)).
- **"Can't see" never blocks.** Incognito and screenshot-protected apps come back blank; Guardian
  alerts instead. A transient AI error (503/timeout) is retried, then skipped — it never closes an
  app.

## Optional: uninstall detection

Code that has been uninstalled can't report itself. `server/cloudflare-worker/` is a free always-on
watchdog (Cloudflare Worker + Cron + KV + Resend) that emails your partner when the phone stops
checking in:

```bash
npm install -g wrangler && wrangler login
```

```bash
cd android/server/cloudflare-worker && wrangler kv namespace create GUARDIAN_KV
```

Paste the printed id into `wrangler.toml`, set `ALERT_EMAIL` there, add your Resend key
(`wrangler secret put RESEND_API_KEY`), then `wrangler deploy` and put the resulting
`https://…/beat` URL into Guardian's **Heartbeat URL** setting. Free tiers cover it comfortably.

## Layout

```
app/src/main/java/com/lockoutprotocol/guardian/
  App.kt                    notification channel + launch-time safety check
  data/       Prefs (EncryptedSharedPreferences), EventLog
  ai/         OllamaClient (prompt + verdict), AlertPolicy (what notifies)
  capture/    FrameQuality (blank/incognito heuristic)
  service/    MonitorService (the loop), AppWatchAccessibilityService, BlockGate,
              Overrides, AutoMonitor, PackageInstallReceiver, ForegroundApp
  tamper/     SettingsGuard, GuardianAdminReceiver, BootReceiver, HeartbeatWorker,
              TamperAlert, SafetyCovenant, DeviceOwnerPolicy
  push/       Pusher (ntfy)
  ui/         MainActivity (dashboard), SetupActivity, SettingsActivity, GuidelinesActivity,
              BlockActivity, LockActivity, ChangePinActivity, NotifyActivity, PledgeActivity,
              LogActivity, Lcars (theme)
server/cloudflare-worker/   optional uninstall/silence watchdog
```

## Known limits

- **FLAG_SECURE / incognito screens capture blank** — handled as a reported blind spot, not a block.
- **Uninstall can't be detected on-device** — that's what the heartbeat server is for.
- **A determined technical owner can defeat it** (safe mode, ADB). Friction plus a witness, not a
  prison.
