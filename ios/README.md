# Lockout Protocol for iOS

**Status: written, not yet built.** This target has never been compiled — it was written on a
Windows machine with no Xcode. It is structurally checked (`python tools/check_ios.py` from the
repo root validates delimiters, declarations, and that the App Group and bundle ids agree across
all five entitlements files, five plists and the project spec), and that is all the verification
anyone should credit it with. Treat the first `xcodegen generate && xcodebuild` as the real test.

The Windows and Android apps, by contrast, are compiled and tested — see the root README.

---

## The one thing to understand first

**On iOS, no app can see another app's screen.** There is no public API for it, there is no
entitlement for it, and the sandbox is not going to be talked out of it. This is not a gap we
haven't got to yet; it is permanent.

So the iOS app cannot do what the desktop and Android apps do. Instead of asking the model a
question about your screen every couple of minutes, it asks a different question once, when you
start a session:

| | Windows / macOS / Android | iOS |
|---|---|---|
| **The question** | "You said *math test prep* — is **this screen** part of it?" | "You said *math test prep* — **which of my apps** should be shut for it?" |
| **How often** | every 30s–10min, all session | once, at the start |
| **What leaves the device** | a JPEG of your screen | your typed task + the names of apps you chose to offer |
| **Granularity** | per screen | per app |
| **Who enforces it** | our overlay | iOS itself |
| **Permissions needed** | screen recording / accessibility | Screen Time |

### What that costs you

**YouTube is either shut or open.** The model never sees which video you opened, so it cannot let
a Khan Academy lecture through and stop a gaming stream. On the desktop that distinction is the
single most valuable thing the app does; here it is simply unavailable. If your distractions are
*inside* otherwise-legitimate apps, the desktop app is the one you want.

The shield is also coarse in time: it goes up for the whole session rather than reacting to what
you actually do.

### What you get instead

**Nothing about your screen is captured, encoded, or transmitted. At all. Ever.** That is not a
policy or a setting, it is a property of the platform, and it is a genuinely better privacy story
than the other three ports can offer even with everything switched off.

**The shield is drawn by iOS, not by us.** It cannot be swiped away, raced by another window, or
defeated by force-quitting our app — which is what three quarters of the tamper-resistance code on
the other platforms exists to prevent. It also cannot lock you out of anything: iOS never shields
the home screen, Settings, Phone, or Messages.

**No accessibility permission, no screen recording permission, no background service, no
keep-alive watchdog.** The app is asleep for the whole session.

---

## Before you can build this: the entitlement gate

The Screen Time APIs are behind `com.apple.developer.family-controls`, which **Apple grants by
hand, per Apple Developer account**. You cannot work around this and neither can we.

1. **You need a paid Apple Developer account** — $99/year. There is no free path: the entitlement
   is not available to a personal team, so even running on your own device requires it.
2. **Request the entitlement** at
   [developer.apple.com/contact/request/family-controls-distribution](https://developer.apple.com/contact/request/family-controls-distribution).
   Apple asks what the app does. It is a digital-wellbeing tool for the account holder's own
   device, which is squarely inside App Store Review Guideline 2.5.15 — but say so in your own
   words, and expect it to take days, not minutes.
3. **Request it for every bundle id separately.** The app *and* each of the three Screen Time
   extensions need it:
   - `com.lockoutprotocol.lockout`
   - `com.lockoutprotocol.lockout.shieldconfig`
   - `com.lockoutprotocol.lockout.shieldaction`
   - `com.lockoutprotocol.lockout.monitor`

   (The widget does not need it — it only reads a file.) Missing one is the classic mistake, and
   it fails in the most confusing way possible: the app builds, sessions start, and *nothing is
   shielded*.
4. **Change the bundle ids to your own reverse-DNS prefix** before requesting anything, or you
   will be asking Apple for entitlements on identifiers you don't own. `ios/project.yml` is the
   only place they are written.

Until step 2 completes, `xcodebuild` for a device will fail at the signing step. The simulator
will build but Screen Time does nothing there, so there is very little to see.

---

## Build

```sh
brew install xcodegen         # the project file is generated, not committed — see below
cd ios
xcodegen generate
open Lockout.xcodeproj
```

Then in Xcode: set your team on all five targets, change the bundle ids and the App Group to your
own prefix, and run on a real device.

`Lockout.xcodeproj` is deliberately **not** committed, unlike the macOS one. Five targets that
must agree about an App Group, a Keychain access group and four separate copies of an entitlement
is exactly the configuration that rots when hand-edited — and every one of those mistakes fails
silently. `project.yml` keeps the wiring reviewable as text.

### The identifiers that must agree

Change these together or the app will run and do nothing:

| Where | What |
|---|---|
| `project.yml` | five `PRODUCT_BUNDLE_IDENTIFIER`s |
| all five `*.entitlements` | `com.apple.security.application-groups` |
| all five `*.entitlements` | `keychain-access-groups` |
| `Lockout/Focus/FocusSession.swift` | `SessionStore.appGroup` |
| `LockoutMonitor/DeviceActivityMonitorExtension.swift` | the hardcoded group string (duplicated on purpose — see the comment there) |

`tools/check_ios.py` verifies all of these match, so run it after any rename.

---

## How a session works

1. **You type a task** and pick a length, a level, and — via the system
   `FamilyActivityPicker` — the apps you are willing to have shut. iOS hands back opaque
   `ApplicationToken`s; the app never learns which apps they are, which is why you cannot type
   a watchlist by hand here.
2. **The model proposes a plan**: which of those apps to shut, and why, in one or two sentences.
3. **You confirm it.** This step exists because the decision is coarse — a wrong call costs you an
   app for ninety minutes, not one interrupted moment — so it is always reviewed before it applies.
   If the model can't be reached, the plan is "shut everything you offered", which is
   `ShieldPlan.Fallback` and is deliberately the strict choice: unlike a block screen, a shield
   cannot trap you.
4. **iOS shields them.** A `DeviceActivitySchedule` is registered for the end time, so the shield
   lifts even if you never open the app again. `SessionStore.current` also expires on read, so a
   phone that was off past the end time still ends cleanly.
5. **If you open a shielded app**, iOS shows the shield: your own words back at you, and two
   buttons.

### The two accountability levels, and where iOS differs

|  | Self-managed | Locked |
|---|---|---|
| "Back to work" | closes, shield stays | same |
| "I'm on task" / "Unshield" | lifts that one app, logged | **needs the passcode** |
| Partner told | no | on every shield hit and unshield |

**The honest limitation:** a shield action extension cannot show UI, so it cannot ask for a
passcode. A locked session's unshield button therefore returns `.defer` — the shield stays up — and
the shield's own text tells you to open Lockout, where a passcode *can* be asked for. The button
does not silently fail; it tells you where to go. Faking success there would be the worst possible
outcome: an unshielded app on a session your partner believes is locked.

---

## The false-alarm signal, free

On the other platforms, teaching the learner requires a deliberate "this was a false alarm" tap.
Here it comes for nothing: **nobody unshields an app they agreed should be shut.** So every
unshield is logged as `feedback: "false_alarm"` against the shield plan that shut it, in the same
`judgements.jsonl` format the other three ports write.

Export it from Settings → Data (there is no `adb pull` on iOS) and feed it to `learner/`. Rows
carry `"platform": "ios"`, and `window_title` is `""` — iOS has no window title to report and
inventing one would poison the learner's title patterns with fiction.

---

## What is not built

- **No content-rules mode.** The original always-on content classifier needs to see the screen, so
  it does not exist here and cannot.
- **No per-screen confidence**, so the learner's confidence calibration has nothing to work with on
  iOS rows. Its allowance mechanism — which is the one that measured well anyway — works fine.
- **No tamper resistance**, because there is nothing to defend: iOS enforces the shield and we
  cannot be force-quit out of it.
- **App Store submission.** Beyond the entitlement, Guideline 2.5.15 requires the app to be
  genuinely a digital-wellbeing tool, which it is, and the Data Safety-equivalent disclosures need
  writing. Nobody has been through review with this.
