# Lockout Protocol (alpha)

An AI accountability monitor for **Android** and **macOS**.

It takes a screenshot of the apps you choose, asks a vision model whether what's on screen breaks
rules you wrote, and if it does: **blocks the app and notifies your accountability partner** — then
makes itself hard to quietly switch off.

> **Alpha.** It works, it's been run daily on real devices, but it is rough around the edges and
> there are no signed release builds — you compile it yourself. Expect false positives while you
> tune your rules.

---

## What it actually does

```
      which app is in front?            ┌──────────────────────────────┐
Android: AccessibilityService  ───────► │  is this app on my watchlist? │
macOS:   NSWorkspace                    └──────────────┬───────────────┘
                                                       │ yes
                                        one screenshot ▼
                                   ┌────────────────────────────────┐
                                   │  vision model (Ollama Cloud)   │
                                   │  "does this break my rules?"   │
                                   └───────────┬────────────────────┘
                                    violation  │  clean → next check
                                               ▼
                          ┌────────────────────────────────────────┐
                          │ block screen over the app               │
                          │ + push notification to your partner     │
                          │ + line in the on-device activity log    │
                          └────────────────────────────────────────┘
```

**Core features**

- **Your rules, in plain English.** The default rules target sexual/suggestive content; edit them to
  whatever you're holding yourself to. The classifier flags both what's *visible* and what your
  *typed text* shows you were looking for ("searched Google Images for …").
- **Blocking that costs something.** Android shows a sticky block screen that keeps coming back
  until you press Dismiss (which closes the offending app) — a reflex swipe won't clear it. macOS
  shows a full-screen block on every display.
- **Someone else finds out.** Alerts go over [ntfy](https://ntfy.sh) — free, no account, no email
  setup. Your partner installs the ntfy app and subscribes to your private topic.
- **Hard to switch off (see [SAFEGUARDS.md](SAFEGUARDS.md)):**
  - Opening the app, changing settings, and dismissing blocks are behind a passcode.
  - Opening system Settings raises a **pledge screen** first.
  - Bouncing out of Guardian's own accessibility / app-info / uninstall pages, and alerting when you
    go there.
  - Alerts when accessibility (Android) or Screen Recording (macOS) is revoked, or device admin is
    removed.
  - macOS relaunches itself within ~10s of any quit or force-quit (KeepAlive LaunchAgent).
  - Android auto-enrolls **newly installed apps** into monitoring, so installing a fresh browser
    isn't a free pass.
  - A self-check at launch alerts your partner if the rules get gutted, the app is put back into
    TEST mode, or alerts are turned off.
- **TEST mode by default.** Everything is evaluated and logged but nothing is blocked until you
  deliberately arm it. Watch the activity log for a day first.
- **Anti-lockout by design.** A screen the AI can't read (incognito, DRM, blank) is *never* a hard
  block — it alerts instead. A transient AI outage never blocks. Block screens always have a working
  exit. You should never be locked out of your own device.

**What it is not:** it is not covert. Install it on a device **you own**, or where the person using
it has knowingly agreed. Secretly monitoring someone else's device is illegal in many places.

---

## Get started (about 20 minutes)

### 1. Get an Ollama Cloud API key

The vision model runs in the cloud, so a phone can use it.

1. Sign up at **[ollama.com](https://ollama.com)** and create an API key.
2. Keep it handy — you'll paste it into the app's Settings. Default model:
   `gemma4:31b-cloud` (any vision-capable cloud model works).

There is a usage cost on Ollama's side — while you are inside a monitored app it checks
continuously (one screenshot per model reply, a couple of seconds apart). Start with a short
watchlist.

### 2. Set up alerts (ntfy) — do this *with* your accountability partner

1. Both of you install **ntfy** ([Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy)
   / [iOS](https://apps.apple.com/us/app/ntfy/id1625396347) / [web](https://ntfy.sh/app)).
2. In Guardian, open **🔔 Set up alerts** (Android) or **Settings** (macOS). It shows a
   private code like `guardian-8fk2j4nx9qla`.
3. Your partner subscribes to that exact code in their ntfy app.
4. Press **Send test alert**. If it lands on their phone, you're done.

The code is the only secret — anyone who knows it can read your alerts, so don't post it anywhere.

### 3. Build and install

- **Android** → [android/README.md](android/README.md)
- **macOS** → [macos/README.md](macos/README.md)

### 4. First run, in this order

1. **Set a passcode.** Give it to your accountability partner, or use one you won't remember — this
   is what stops you from casually changing the rules later.
2. **Grant permissions** from the setup screen (accessibility + overlay + device admin + battery on
   Android; Screen Recording on macOS).
3. **Paste your Ollama API key** — Android: *AI · advanced settings*; macOS: *Settings*.
4. **Pick the apps to watch.** Browsers, social apps, image-heavy apps, app stores, and any emulator
   or mirroring app. Don't add password managers or banking apps.
5. **Edit your rules.** Plain English. Be specific about what you want flagged.
6. **Leave it in TEST mode for a day** and read the activity log. Tighten or loosen the rules until
   the verdicts look right.
7. **Arm it** — uncheck TEST MODE in Settings. Now it blocks.

### 5. Optional: catch an uninstall

Nothing running *on* the device can report that it was uninstalled. If you want that covered, deploy
the tiny heartbeat watchdog in [android/server/cloudflare-worker](android/server/cloudflare-worker)
(free Cloudflare Worker + Resend); it emails your partner when the device stops checking in.

---

## Honest limitations

- **Detection is probabilistic.** It depends on the model and on how you wrote your rules. It samples
  screens; something can appear and vanish between samples.
- **Some screens can't be read.** Incognito windows, DRM video, and screenshot-protected apps come
  back blank. Guardian alerts on this rather than blocking, so it's a known, reported blind spot —
  not a silent one.
- **A determined technical owner can defeat it.** Safe mode, ADB, a second device, reinstalling the
  OS. This is friction plus a witness, not a prison.
- **Alpha-quality UI.** Functional, not pretty.
- **Cost.** Every check is a vision-model inference on your Ollama account.

## Repo layout

```
android/    Kotlin app (minSdk 34)          — see android/README.md
macos/      SwiftUI app (macOS 14+)         — see macos/README.md
SAFEGUARDS.md  what not to weaken, and why
```

## Licence

MIT — see [LICENSE](LICENSE). No warranty. Use it on your own devices, with consent.
