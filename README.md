# Lockout Protocol

A focus monitor for Windows, macOS, Android and iOS.

You type what you are working on — `revising integration by parts for Friday's test` — and pick a
length. Every couple of minutes it looks at whichever app you are in, asks a model whether that
screen is part of that task, and interrupts you when it clearly is not.

The difference from a normal app blocker is that it judges the screen, not the app. A lecture on
YouTube is part of maths revision. A gaming stream on YouTube is not. An app-list blocker has to
allow both or block both.

---

## Status

| | Windows | Android | macOS | iOS |
|---|---|---|---|---|
| Compiles | yes | yes | yes (Xcode 16.4) | not attempted |
| Tests | 109 | 58 | 12 | none written |
| Packaged download | yes | yes | build it yourself | not possible yet |

Every "yes" above is a job in [`.github/workflows/build.yml`](.github/workflows/build.yml) that runs
on each push. To run whatever your own machine can:

```sh
python tools/verify.py
```

It prints PASS, FAIL or SKIP for each check and never lets a skip read as a pass.

**iOS is written but has never been built.** Apple grants the `family-controls` entitlement by
hand, per developer account, so no CI runner can hold it. It also works differently from the other
three — see [Privacy](#privacy) and [ios/README.md](ios/README.md).

Nobody has yet run the macOS app on a real Mac and watched it block something. The tests cover the
logic, not the screen-capture path.

---

## Downloads

| Platform | File |
|---|---|
| Windows 10/11 | [Releases](../../releases/latest) → `LockoutProtocol-windows.zip`. Unzip and run `LockoutProtocol.exe`. Unsigned, so SmartScreen warns once. |
| Android 14+ | [Releases](../../releases/latest) → `.apk`. Debug-signed; allow "install unknown apps" for your browser. |
| macOS 14+ | `cd macos && xcodegen generate && open Guardian.xcodeproj`. Needs Xcode 16. |
| iOS 16+ | See [ios/README.md](ios/README.md). |

---

## Architecture

Four apps, one shared design. Each platform has its own capture and blocking mechanism, but the
session model, the classifier prompt, the judgement log and the learned-policy format are the same
everywhere.

```
 ┌─ you ─────────────────────────────────────────────────────────────┐
 │  task: "revising integration by parts"    50 min    self-managed  │
 │  apps: your default watchlist, ± anything just for today          │
 └────────────────────────┬──────────────────────────────────────────┘
                          │ starts a session
                          ▼
 ┌─ monitor loop ────────────────────────────────────────────────────┐
 │  every N seconds, only while a session is running:                │
 │    1. which app is in front? is it on this session's watchlist?   │
 │    2. capture one frame of it                                     │
 │    3. ask the model: is this screen part of the declared task?    │
 └────────────────────────┬──────────────────────────────────────────┘
                          ▼
        ┌─────────────────┴─────────────────┐
        │                                   │
    on task                             off task
   log, continue                            │
                                            ▼
                            ┌─ block ────────────────────────┐
                            │  self-managed: dismiss freely  │
                            │  locked: passcode + partner    │
                            └────────────────────────────────┘
```

**Sessions.** Monitoring begins and ends with a session. The watchlist is stored as a delta over
your saved defaults, so apps added or excused for one afternoon do not change your settings.

**Two accountability levels**, chosen per session:

| | Self-managed | Locked |
|---|---|---|
| Blocks you | yes | yes |
| Dismissing a block | no passcode | passcode |
| Ending the session early | any time | passcode |
| Partner notified | no | on every block and override |

Closing a blocked app never needs a passcode, at either level. That is the anti-lockout rule and it
is not configurable.

**Providers.** One transport layer with four request shapes: Ollama (`/api/chat`), OpenAI-style
(`/v1/chat/completions`), Anthropic (`/v1/messages`), and anything OpenAI-compatible at a URL you
supply. Retry, key fail-over, and the rule that a backend problem never blocks you, are shared code.

**Per platform:**

| | Foreground app | Capture | Block |
|---|---|---|---|
| Windows | `GetForegroundWindow` | GDI screenshot | always-on-top Tk overlay |
| macOS | `NSWorkspace` | ScreenCaptureKit | full-screen window at screen-saver level |
| Android | AccessibilityService | `takeScreenshot()` | sticky Activity + `BlockGate` |
| iOS | — | — | Screen Time shield, drawn by iOS |

```
windows/     Python + Tk. Tray panel, dashboard, system-wide overlay.
android/     Kotlin. Home-screen widget, accessibility capture.
macos/       Swift + SwiftUI. Menu-bar item, ScreenCaptureKit.
ios/         Swift. Screen Time shields — read its README first, it works differently.
learner/     Offline Python. Turns "that was a false alarm" into a policy the apps read.
tools/       verify.py, the structural checkers, the Windows packager.
```

The four clients share one judgement-log format and one policy format.
[`windows/tests/test_policy_contract.py`](windows/tests/test_policy_contract.py) reads the other
platforms' source as text to check the shared constants have not drifted, because nothing compiles
all four together. It has already caught one real bug.

---

## Privacy

### What this app does

Nothing is sent anywhere except to the model provider you configure. There is no telemetry, no
analytics, no account, and no server of ours involved at any point. The project has no backend.

Screenshots are never written to disk. A frame is captured, encoded, sent, and discarded.

**Capture only happens during a session.** Not captured-and-discarded when idle — not captured at
all. That is a branch in the monitor loop and a test
([`test_idle_never_touches_the_screen`](windows/tests/test_monitor_flow.py)), not a policy
statement.

Two logs are kept, both local:

- `activity.log` — a line per check, for you to read.
- `judgements.jsonl` — the same events as structured rows, for the end-of-session summary and the
  offline learner. Never uploaded; on iOS you export it by hand if you want to use it.

API keys go in the OS credential store (DPAPI on Windows, Keychain on macOS and iOS,
EncryptedSharedPreferences on Android), never a config file.

Alerts, if you enable them, go to [ntfy](https://ntfy.sh) as a short text message: the app name and
the model's one-line reason. No screenshot. The topic string is the only secret.

### What your provider sees

This is the part that actually varies, so choose deliberately.

| Provider | What leaves your device | Who can see it |
|---|---|---|
| Ollama on this machine | nothing | nobody |
| Ollama on your own computer (phone → LAN) | a JPEG of your screen, over your Wi-Fi | nobody outside your network |
| LM Studio / llama.cpp / vLLM, local | nothing, or your LAN only | nobody outside your network |
| Ollama Cloud | a JPEG of your screen, plus your task text | ollama.com, under their terms |
| OpenAI | a JPEG of your screen, plus your task text | OpenAI, under their terms |
| Anthropic | a JPEG of your screen, plus your task text | Anthropic, under their terms |
| Your own gateway | whatever you point it at | you |

A local model is the private option and the free one. If your machine can run a vision model, use
it: `ollama pull qwen3-vl:8b`, then point the app at `http://127.0.0.1:11434`.

On Android, "local" means a model on your own computer reached over Wi-Fi. Start Ollama with
`OLLAMA_HOST=0.0.0.0` and give the phone your machine's LAN address.

Whichever you choose, the screenshot is of whichever watched app is in front, so it can contain
anything that app is showing. Do not put a password manager or a banking app on the watchlist.

### iOS is different

No iOS app can see another app's screen. There is no API for it and there will not be one. So the
iOS app does not screenshot anything: it asks the model *which of your apps to shut for this task*,
and Apple's Screen Time shields them.

That is coarser — YouTube is shut or open, with no way to tell a lecture from a stream — and
strictly more private, because the only thing that leaves the device is your typed task and a list
of app names you chose to offer. [ios/README.md](ios/README.md) has the full trade-off.

### What it is not

Not covert. Install it on a device you own, or where the person using it has agreed. Secretly
monitoring someone else's device is illegal in many places.

---

## Getting started

### 1. Choose a model provider

Settings → Model provider. Every option is listed with what it costs and what it sees. Press **Test
connection**: it tells you immediately whether the server is reachable and whether the model you
named is actually there, rather than failing forty minutes into a session.

### 2. Pick a default watchlist

Browsers, social apps, video, games, shopping. Not password managers, not banking apps.

Only apps on this list are ever captured, and only while a session is running.

### 3. Run one session in TEST mode

TEST mode evaluates and logs everything but blocks nothing. Do a normal hour of work, then read the
activity log and see whether the verdicts match what you were actually doing. Adjust, then turn TEST
mode off to arm blocking.

Be specific in the task box. `revising integration by parts for Friday's calc test` works; `study`
does not.

### 4. Optional: alerts, for locked sessions

Only needed if you want the locked level.

1. You and your accountability partner both install [ntfy](https://ntfy.sh) (Android, iOS, or web).
2. Settings shows a private code like `lockout-8fk2j4nx9qla`. They subscribe to exactly that.
3. Press **Send test alert**.

That code is the only secret. Anyone who knows it can read your alerts.

### Running from source

Windows (Python 3.12):

```sh
python -m pip install pillow pystray pywin32
cd windows && python run_guardian.pyw
cd windows && python run_tests.py          # tests
```

Android (JDK 17 + Android SDK):

```sh
cd android
./gradlew :app:assembleDebug
./gradlew :app:testDebugUnitTest
```

Package a Windows build:

```sh
python -m pip install pyinstaller
python tools/build_windows.py              # → dist/LockoutProtocol/
```

---

## False alarms, and the learner

The failure that matters in a focus tool is the false alarm. Interrupting real work twice in an
afternoon is how the app gets uninstalled, after which it protects nothing.

So the classifier is biased towards "on task", and counts supporting work — a lecture, a
documentation page, a forum thread, a study-group chat — as part of the job. That bias is pinned by
a test.

[`learner/`](learner/) goes further. It reads the decision log, learns from blocks you marked wrong,
and compiles one portable `focus_policy.json` that all four apps read. Measured over 24 simulated
days:

| | before | after |
|---|---|---|
| false-alarm rate | 49.0% | 6.9% |
| missed-violation rate | 13.2% | 25.3% |

The second number got worse, and that is the more useful result. The ablation in
[learner/README.md](learner/README.md) shows the allowance mechanism produces most of the
improvement at no recall cost, and the confidence calibration causes the entire regression — so the
recommendation is to ship the first and keep the second behind a flag. All figures are from
synthetic data.

It is off by default. A self-control tool that learns from you can be taught to stop stopping you,
so there are limits on how far it can loosen: rate limits, repeated evidence across separate days,
expiry, a hard ceiling the app enforces regardless of what the policy file asks for, and an
integrity score your partner can be alerted on. Those bound the damage rather than removing it, and
the README says so with numbers.

---

## Also here

The original content-rules mode — an always-on classifier checking screens against written
guidelines — is still present, opt-in and off by default under Settings. Turning it on means
screenshots are taken outside sessions too.

[SAFEGUARDS.md](SAFEGUARDS.md) documents what must not be weakened and why, including the
anti-lockout guarantees and the rules for the learner.

## Licence

See [LICENSE](LICENSE).
