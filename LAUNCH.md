# Launch copy

Copy-paste ready. Everything here is written to be **true today** — Windows, Android and macOS build
and pass their tests in CI; iOS is written but unbuilt. See the note at the bottom before you
launch, because downloads exist for only two of the three that build.

---

## The one-liner

Pick one. All under Product Hunt's 60-character tagline limit.

| | Tagline | Chars |
|---|---|---|
| **A** | Tell it what you're working on. It checks if you are. | 52 |
| B | An AI that watches your screen for *you*, not on you | 52 |
| C | Focus blocker that reads the screen, not the app name | 53 |
| D | It knows a lecture from a gaming stream on the same site | 56 |

**A** is the recommended one: it's the whole product in nine words, uses the user's own voice, and
the second sentence lands as a small joke that also happens to be the feature.

---

## Product Hunt

### Tagline
> Tell it what you're working on. It checks if you are.

### Description (the ~260-char field)
> You type "revising integration by parts for Friday's test", pick 50 minutes, and start. Every two
> minutes it looks at the app you're in and asks a model whether that screen is part of *that task*.
> YouTube lecture: fine. YouTube gaming stream: blocked.

### First comment (the maker's post — this is what people actually read)

> Hi PH 👋
>
> Every focus app I've used blocks *apps*. But my problem was never Chrome — it was what I opened in
> Chrome. Blocking YouTube also blocks the lecture I need. Allowing it allows everything.
>
> So this one blocks *screens*. You tell it what you sat down to do, in your own words, and every
> couple of minutes it asks a vision model: **"is this screen part of that?"** A Khan Academy video
> is on task. A gaming stream on the same site isn't. Same app, opposite answers.
>
> Three things I'd want to know if I were you:
>
> **1. It only watches during a session.** Not "watches and discards" — when no session is running,
> no screenshot is taken at all. That's a test in the repo, not a promise in a privacy policy.
>
> **2. You pick the model, and it can be one that never leaves your machine.** Local Ollama, Ollama
> Cloud, OpenAI, Anthropic, or anything OpenAI-compatible. Point it at a local model: zero running
> cost, and no screenshot ever leaves the device.
>
> **3. It cannot lock you out.** Closing a blocked app never needs a passcode, at any level. A
> screen the model can't read is never a block. A model that's down or out of credit is never a
> block. There are eight tests whose only job is to prove nothing except a clean "off task" ever
> blocks you.
>
> Two levels: **self-managed** (it interrupts you and logs it, but you can wave it away) and
> **locked** (passcode to override, and your accountability partner gets pinged on every block *and*
> every override).
>
> The part I found most interesting to build: the classifier is deliberately biased *towards*
> "on task". A missed frame of scrolling costs ten seconds; a false alarm interrupts real work, and
> two of those in an afternoon and you uninstall the thing — at which point it protects nothing. So
> it counts supporting work — a lecture, a forum thread, a study-group chat — as part of the job.
> There's also an experimental learner that reads your "that was a false alarm" presses. It cut
> false alarms from 49% to 6.9% in simulation, and made missed distractions *worse* (13% → 25%).
> Both numbers are in the repo, because the second one is the interesting one.
>
> Free, open source, self-hosted models supported. **Windows, Android and macOS build and pass
> their tests in CI**; iOS is written but unbuilt — it needs an Apple entitlement granted by hand
> per developer account. The README has an honest per-platform status table rather than four green
> ticks.
>
> Happy to answer anything, especially if you think the false-alarm trade-off is wrong.

### Topics
`Productivity` · `Open Source` · `Artificial Intelligence` · `Windows` · `Android`

---

## Show HN

**Title** (HN dislikes marketing voice; this is deliberately flat):

> Show HN: A focus blocker that reads the screen instead of the app name

**Body:**

> Every focus blocker I tried worked on app or domain lists, which never matched the actual problem.
> YouTube isn't the distraction — the gaming stream is; the lecture on the same site is the work.
>
> This takes a plain-English task ("revising integration by parts for Friday's test") and every N
> seconds sends one screenshot of the foreground app to a vision model with the question "is this
> screen part of that task?". Off-task screens get an interruption. Same app, opposite verdicts
> depending on what's on it.
>
> Design notes that might be worth discussing:
>
> - **The prompt is biased towards "on task"**, which is the opposite of what you'd naively want.
>   The asymmetry comes from the cost function: a miss costs seconds, a false alarm costs the
>   install. It explicitly counts supporting work (docs, a lecture, a forum thread) as on-task.
> - **Failure modes fail open.** Unreadable screen, DRM frame, unparseable reply, 503, out of
>   quota, elevated process we can't query — all log and move on. There are eight tests whose only
>   purpose is asserting that nothing but a clean "off task" can block.
> - **Provider is pluggable** — Ollama (local or cloud), OpenAI, Anthropic, anything
>   OpenAI-compatible. One transport layer, four request shapes, and the retry/key-failover policy
>   shared across all of them.
> - **Nothing is captured outside a session.** Enforced by a branch and pinned by a test, because
>   "we don't store it" is not the same claim as "we don't take it".
> - **iOS is a different product on purpose.** No app can see another app's screen on iOS, so
>   instead of "is this screen on task?" the model answers "which of my apps should be shut for this
>   task?", and iOS's own Screen Time shield enforces it. Coarser (YouTube is all-or-nothing), and
>   strictly more private (nothing about your screen leaves the device, ever).
> - **An offline learner** reads the false-alarm log and compiles a portable policy all four clients
>   read. Measured on synthetic data: false alarms 49% → 6.9%, missed distractions 13% → 25%. The
>   ablation says the allowance mechanism gets most of the win at zero recall cost and the
>   confidence calibration causes all of the regression, so the recommendation is to ship one and
>   flag the other.
>
> Windows (Python/Tk), Android (Kotlin) and macOS (SwiftUI) compile and pass their tests in CI —
> 109, 58 and 12. iOS is written and structurally checked but unbuilt: Apple grants the
> `family-controls` entitlement by hand per developer account, so no CI runner can hold it. The
> README says so rather than claiming four platforms.
>
> `python tools/verify.py` runs everything the current machine can and prints PASS/FAIL/SKIP without
> letting a skip look like a pass.

---

## Reddit (r/selfhosted, r/LocalLLaMA, r/productivity)

r/LocalLLaMA and r/selfhosted care about the local-model angle, so lead with it:

> **A focus blocker where the model can be a local Ollama, and nothing leaves your machine**
>
> Made this because app-list blockers never matched my actual problem: I don't need YouTube blocked,
> I need the gaming stream blocked and the lecture allowed.
>
> You type what you're working on. Every couple of minutes it screenshots the foreground app and
> asks a vision model "is this part of that task?". Point it at `http://127.0.0.1:11434` with
> `qwen3-vl:8b` and the running cost is zero and no screenshot ever leaves the box. Ollama Cloud,
> OpenAI, Anthropic and anything OpenAI-compatible also work if you'd rather.
>
> On Android, "local" means a model on your own desktop over Wi-Fi — start Ollama with
> `OLLAMA_HOST=0.0.0.0` and give the phone your LAN address.
>
> Only captures while a session is running (that's a test, not a policy), can't lock you out, and
> there's an offline learner that turns your "false alarm" presses into a policy that stops the same
> interruption happening twice. Windows, Android and macOS build and test green in CI; iOS is
> written but unbuilt.

For r/productivity, drop the local-model paragraph and lead with the false-alarm trade-off instead —
that audience cares about whether it will annoy them, not about inference.

---

## X / Twitter thread

**1/**
> Every focus app blocks apps.
>
> My problem was never Chrome. It was what I opened in Chrome.
>
> So I built one that blocks *screens*. 🧵

**2/**
> You type what you sat down to do:
>
> "revising integration by parts for Friday's test"
>
> Every 2 minutes it looks at the app you're in and asks a vision model: is this screen part of that?

**3/**
> Khan Academy video → on task.
> Gaming stream → blocked.
>
> Same site. Opposite answers. No app-list blocker can do that.

**4/**
> The counterintuitive bit: the prompt is biased *towards* letting you through.
>
> A missed frame of scrolling costs 10 seconds.
> A false alarm interrupts real work — and two of those and you uninstall it.
>
> Then it protects nothing.

**5/**
> It only watches during a session. Not "watches and discards" — no screenshot is taken at all when
> no session is running.
>
> That's a test in the repo, not a line in a privacy policy.

**6/**
> Your model, your choice. Local Ollama = zero cost, nothing leaves the machine.
>
> And it can't lock you out: closing a blocked app never needs a passcode, and anything the model
> can't read is never a block.

**7/**
> Two levels:
>
> · self-managed — it interrupts you, you can wave it away
> · locked — passcode to override, and your accountability partner is pinged on every block *and*
>   every override

**8/**
> There's also an experimental learner that reads your "that was a false alarm" taps.
>
> False alarms: 49% → 6.9%
> Missed distractions: 13% → 25% (worse)
>
> Both numbers are in the repo. The second one is the interesting one.

**9/**
> Free and open source. Windows, Android and macOS build and test green in CI; iOS is written but
> needs an Apple entitlement first — the README has a per-platform status table instead of four
> green ticks.
>
> [link]

---

## The 30-second pitch, spoken

> Focus blockers work on app lists, which is the wrong unit. YouTube isn't the distraction — the
> gaming stream is, and the lecture on the same site is the work. So this one takes a plain-English
> description of what you're doing and checks the actual screen against it every couple of minutes.
> Same app, opposite verdicts. You choose the model, including a local one that never sends anything
> off your machine, and it only looks while a session is running. Two accountability levels: one
> where you can wave it away, one where overriding needs a passcode and a friend gets told.

---

## Differentiators, if you need them as bullets

- **Screen-level, not app-level.** The only one of these that can tell a lecture from a stream on
  the same domain.
- **Session-scoped capture.** Nothing is looked at outside a session you started. Tested, not
  promised.
- **Bring your own model, including a local one.** Zero running cost and zero data egress if you
  want it.
- **Two accountability levels, per session.** Not a global setting you forget you set.
- **Cannot lock you out**, by design and by test.
- **A watchlist you can bend for one afternoon** without editing your permanent settings.
- **Three-second start** from a menu-bar item, tray panel, or home-screen widget.
- **The false-alarm problem is treated as the main problem**, with a measured learner and a
  published scorecard that includes the number that got worse.

---

## Likely questions, with honest answers

**"Isn't this spyware?"**
It's self-binding software you install on your own device. It captures only during a session you
started, sends only to a provider you chose (which can be your own machine), and the repo has a
`SAFEGUARDS.md` explaining what may not be weakened and why. Installing it on someone else's device
without their knowledge is illegal in a lot of places and the README says so.

**"What does it cost to run?"**
Nothing, with a local model. With a hosted one it's one small vision call per check — the interval
is the cost dial, and the UI says so next to the setting.

**"How often does it get it wrong?"**
Often enough that reducing it is the main design constraint. That's why the prompt defaults to "on
task", why supporting work counts, and why there's a learner. The simulated numbers are published,
including the one that regressed. Real-world numbers don't exist yet, and the learner's README says
that plainly.

**"Why is iOS different?"**
Because no iOS app can see another app's screen, and none ever will. iOS uses Apple's Screen Time
shields instead: the model picks which apps to shut for your task, and iOS enforces it. Coarser, and
strictly more private.

**"Is it done?"**
No. Windows, Android and macOS build and pass their tests on every push; iOS is written but unbuilt.
Nobody has yet run it on a Mac and watched it block something in anger, either — the tests cover the
logic, not the capture path. The README's status table distinguishes "passed a test" from "looks
right".

---

## Before you post this

**Three platforms build; iOS doesn't, and downloads exist for two.** macOS compiles and tests
green in CI but ships unsigned, so there is no download for it — people build it themselves.
That's normal for a dev-audience launch and awkward for a general one. So:

1. **Launch now.** The copy above already says "Windows, Android and macOS build green; iOS is
   written but unbuilt". Lowest risk, and an honest status table tends to *earn* goodwill on HN.
2. **Notarise a macOS build first** if you want three downloads instead of two. Needs a paid Apple
   account and an afternoon.
3. **Don't gate the launch on iOS.** Apple grants `family-controls` by hand, per account, and it
   can take days.

Worth doing regardless: **actually run it on a Mac.** CI proves it compiles and the logic tests
pass; it does not prove ScreenCaptureKit grabs a frame or that the menu-bar item behaves.

Also worth doing before you post: **tag a release** so the download links in the README actually
resolve. `git tag v0.1.0 && git push --tags` triggers the workflow in
`.github/workflows/build.yml`, which builds the Windows bundle and the APK and attaches both.
