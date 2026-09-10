# Lockout Protocol

**Say what you sat down to do. It checks whether you're actually doing it.**

You type `revising integration by parts for Friday's test`, pick 50 minutes, and press start. Every
couple of minutes it looks at whichever app you're in, asks a model *"is this screen part of that?"*,
and if the answer is clearly no, it interrupts you.

For **Windows**, **macOS**, **Android**, and **iOS**.

```
      you: "revising integration by parts for Friday's test"   ·   50 min   ·   locked
                                    │
                        every 2 min ▼   (only while a session is running)
                    ┌───────────────────────────────────────┐
                    │  which app is in front?               │
                    │  is it on my watchlist for today?     │
                    └───────────────┬───────────────────────┘
                          one frame ▼
                    ┌───────────────────────────────────────┐
                    │  a model you chose — local or hosted  │
                    │  "is this screen part of that task?"  │
                    └───────┬───────────────────────┬───────┘
                    on task │                       │ off task
                            ▼                       ▼
                     logged, next check      ┌──────────────────────────┐
                                             │  YOU SAID YOU WERE:      │
                                             │  revising integration…   │
                                             │                          │
                                             │  [ Not now · close it ]  │
                                             │  [ Override · passcode ] │
                                             └──────────────────────────┘
                                                 + your partner is told
```

> **Alpha.** Windows, Android and macOS are compiled and tested in CI (see [Status](#status)). iOS is
> written and has never been built — it needs an Apple entitlement no CI runner can hold. Expect
> rough edges, and read the [honest status table](#status) before trusting any of it.

---

## Downloads

| Platform | Get it | Notes |
|---|---|---|
| **Windows 10/11** | [Releases](../../releases/latest) → `LockoutProtocol-windows.zip` | Unzip, run `LockoutProtocol.exe`. Unsigned, so SmartScreen warns once — More info → Run anyway. |
| **Android 14+** | [Releases](../../releases/latest) → `.apk` | Debug-signed. Allow "install unknown apps" for your browser. |
| **macOS 14+** | build it: `cd macos && xcodegen generate && open Guardian.xcodeproj` | Notarising a distributable needs a paid Apple account. |
| **iOS 16+** | build it: see [ios/README.md](ios/README.md) | Needs Apple's `family-controls` entitlement, granted by hand per developer account. |

Running from source instead: [Windows](#run-from-source), [macOS](macos/README.md),
[Android](android/README.md), [iOS](ios/README.md).

---

## What makes it different

**It only watches during a session.** Not "watches and discards" — when no session is running, no
screenshot is taken at all. That's a test, not a promise:
`windows/tests/test_monitor_flow.py::test_idle_never_touches_the_screen`.

**It judges the screen, not the app.** YouTube showing a lecture on your topic is on task. YouTube
showing a gaming stream isn't. Blunt app blockers can't tell those apart; that distinction is the
whole reason this exists.

**Your model, your choice — including one that never leaves your machine.** Local Ollama, Ollama
Cloud, OpenAI, Anthropic, or anything OpenAI-compatible (LM Studio, llama.cpp, vLLM, OpenRouter, a
company gateway). Point it at a local model and the running cost is zero and nothing is uploaded.

**Two levels of accountability, and you pick per session.**

| | Self-managed | Locked |
|---|---|---|
| It blocks you | yes | yes |
| Dismissing it | you, no passcode | **passcode required** |
| Ending early | you, any time | **passcode required** |
| Partner notified | no | every block and every override |

Start with self-managed. The interruption and the log are the accountability; you don't need a
passcode to benefit. `Locked` is for when *"I'll just check one thing"* has already won too often —
give the passcode to someone else, or use one you won't remember.

**It cannot lock you out.** Closing a blocked app never needs a passcode, at any level. A screen the
model can't read is never a block. A model that's down, out of quota, or unreachable is never a
block. Those aren't fail-safes bolted on — they're
tested directly, in [`TestNothingElseEverBlocks`](windows/tests/test_monitor_flow.py) —
eight cases whose only job is to prove nothing else ever blocks.

**A watchlist you can bend for one afternoon.** Your default list plus anything you add just for
today, minus anything you excuse just for today — without editing your permanent settings and
forgetting to put them back.

**Start it in three seconds.** macOS menu-bar item, Windows tray panel, Android home-screen widget,
iOS home-screen and Lock Screen widget. A focus tool that takes four taps to arm gets used on the
days you least need it.

---

## Status

Nothing below is aspirational. "Verified" means a command was run and passed.

| | Windows | Android | macOS | iOS |
|---|---|---|---|---|
| Compiles | ✅ | ✅ | ✅ Xcode 16.4 | ⚠️ not attempted |
| Unit tests | ✅ 109 | ✅ 58 | ✅ 12 | — none written |
| Runs end to end | ✅ | ✅ APK builds | ✅ `xcodebuild test` | ⚠️ |
| Packaged build launches | ✅ | ✅ | — unsigned only | ⚠️ |
| Structure checked | ✅ | ✅ | ✅ | ✅ |

Every ✅ above is a job in [`.github/workflows/build.yml`](.github/workflows/build.yml) that runs on
every push — so the table goes red on its own if it stops being true.

Plus the [learner](learner/): 71 tests, and a measured before/after scorecard.

Run everything your machine can:

```sh
python tools/verify.py
```

It prints `PASS` / `FAIL` / `SKIP` and never lets a skip look like a pass. On Windows with a JDK 17
and an Android SDK you should see **8 passed, 0 failed, 2 skipped** — the two skips being the macOS
and iOS Xcode builds, which need a Mac.

**What "not attempted" means for iOS:** the Swift is structurally checked —
`tools/check_ios.py` verifies delimiters, that every referenced symbol exists, and that the App
Group and bundle ids agree across all five entitlements files, five plists and the project spec.
That catches typos, not type errors. It cannot be built in CI because Apple grants the
`family-controls` entitlement by hand, per developer account; see [ios/README.md](ios/README.md).

For calibration on how much that gap matters: macOS was in exactly this state one commit ago, and
its first real compile found **one** error — an ambiguous `String.init` overload in a chained
expression. Structural checking is worth something. It is not worth as much as a compiler.

---

## Get started

### 1. Pick a model provider

| | Cost | Privacy | Setup |
|---|---|---|---|
| **Ollama on this machine** | free | nothing leaves the device | install [Ollama](https://ollama.com), `ollama pull qwen3-vl:8b` |
| **Ollama Cloud** | metered | screenshots go to ollama.com | sign up, paste an API key |
| **OpenAI / Anthropic** | metered | screenshots go to them | paste an API key |
| **Anything OpenAI-compatible** | yours | yours | paste a base URL ending in `/v1` |

A local model is the right default if your machine can run one. Settings → **Test connection** tells
you immediately whether it's reachable, rather than forty minutes into a session.

On **Android and iOS**, "local" means a model on *your computer*, reached over Wi-Fi — start Ollama
with `OLLAMA_HOST=0.0.0.0` and give the phone your machine's LAN address. iOS doesn't need a vision
model at all; see [ios/README.md](ios/README.md) for why.

### 2. If you want the locked level: set up alerts

Do this *with* your accountability partner.

1. Both install **ntfy** ([Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy) ·
   [iOS](https://apps.apple.com/us/app/ntfy/id1625396347) · [web](https://ntfy.sh/app)).
2. Settings shows a private code like `lockout-8fk2j4nx9qla`. They subscribe to exactly that.
3. Press **Send test alert**. If it lands, you're done.

That code is the only secret — anyone who knows it can read your alerts, so don't post it anywhere.

### 3. Set a default watchlist, then run a session in TEST mode

Browsers, social apps, games, video, shopping. Not your password manager or your bank.

Leave **TEST mode** on for the first session: everything is evaluated and logged, nothing is
blocked. Read the activity log afterwards and see whether the verdicts match what you were actually
doing. Then arm it.

Being specific in the task box matters more than anything else here. `revising integration by parts
for Friday's calc test` works; `study` does not.

---

## Run from source

**Windows** (Python 3.12):

```sh
python -m pip install pillow pystray pywin32
cd windows && python run_guardian.pyw
```

Tests: `cd windows && python run_tests.py`

**Android** (JDK 17 + Android SDK):

```sh
cd android
./gradlew :app:assembleDebug          # APK in app/build/outputs/apk/debug/
./gradlew :app:testDebugUnitTest
```

**Package a Windows build yourself:**

```sh
python -m pip install pyinstaller
python tools/build_windows.py         # → dist/LockoutProtocol/
```

---

## The experimental learner

The failure mode that kills a focus tool is the **false alarm** — it interrupts you while you're
working, twice in an afternoon, and you uninstall it. So the classifier is deliberately biased
towards "on task" and counts supporting work (a lecture, a forum thread, a study-group chat) as part
of the job. That bias is [pinned by a test](windows/tests/test_focus.py).

[`learner/`](learner/) goes further: it reads the decision log, learns from the blocks you marked
wrong, and writes one portable `focus_policy.json` that all four apps read. Measured on 24 simulated
days:

| | before | after |
|---|---|---|
| false-alarm rate | 49.0% | **6.9%** |
| missed-violation rate | 13.2% | **25.3% — worse** |

Both numbers are real and both matter. The recommendation in
[learner/README.md](learner/README.md) is to ship the *allowances* mechanism (which cut false alarms
to 19.4% at **zero** recall cost) and keep *threshold calibration* behind a flag, because
calibration caused the entire regression. All numbers are from synthetic data; that's stated there
too.

It is **off by default**, because a self-control tool that learns from you can be taught to stop
stopping you. The anti-gaming design — rate limits, repeated-evidence requirements, expiry, a hard
0.85 ceiling the app enforces regardless of what the policy file asks for, and an integrity score
your partner can be alerted on — is documented there, along with the measurement showing it *bounds*
the damage rather than eliminating it.

---

## What this is not

**Not covert.** Install it on a device **you own**, or where the person using it has knowingly
agreed. Secretly monitoring someone else's device is illegal in many places.

**Not a content filter** any more, though it can still be one: the original always-on
content-safety classifier is still here, opt-in and off by default, under Settings → *Also enforce
content rules*. Turning it on means screenshots are taken outside sessions too. See
[SAFEGUARDS.md](SAFEGUARDS.md).

**Not free to run** unless you use a local model. Every check is one screenshot and one model call,
so the interval is your cost dial.

---

## Layout

```
windows/     Python + Tk. Tray panel, mini dashboard. Verified.
android/     Kotlin. Home-screen widget, accessibility capture. Verified.
macos/       Swift + SwiftUI. Menu-bar item, ScreenCaptureKit. Verified.
ios/         Swift. Screen Time shields instead of screen reading — read its README first.
learner/     Offline, stdlib-only Python. The false-alarm learner and its scorecard.
tools/       verify.py and the structural checkers.
```

The four apps share one judgement-log format and one learned-policy format, and
[`windows/tests/test_policy_contract.py`](windows/tests/test_policy_contract.py) reads the other
platforms' source as text to prove the constants haven't drifted. That's unusual, and it's the
point: nothing compiles all four together, so nothing else would catch it. It has already caught one
real bug — a lower-casing mismatch that silently disabled learning on macOS entirely.

## Licence

See [LICENSE](LICENSE).
