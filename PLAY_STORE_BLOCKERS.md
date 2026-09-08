# Play Store & App Store — Blockers List

**Compiled:** 2026-09-07
**Sources:** (a) direct inspection of this repo, (b) a policy research pass (full report:
`~/.openclaw/outsource/runs/2026-09-07T2059-lockout-protocol-gemini-r2.out`).

Two kinds of claim appear below and they are **not** equally reliable:

- ✅ **VERIFIED IN REPO** — I opened the file and the line is there. Trust these.
- 📋 **POLICY (RE-CHECK)** — from the research pass. Policy text and dates change; the report
  itself flagged the 2026 target-SDK deadline as inferred from Google's annual cadence, not read
  off the page. **Confirm each against the linked Google/Apple page before acting.**

---

## The headline

The Play Store blocker is **not** the missing signing config. It is that three of the app's
deliberate design features are, as currently written, the specific things Google's malware and
device-abuse policies name. The app has to be **re-scoped for Play**, not just re-packaged.

The good news: none of this touches the core loop (foreground detection → vision classification →
block → alert). What has to go is the *tamper-resistance* layer, and what has to be added is
*disclosure*.

---

## A. Android — blockers, ranked

### A1. Anti-uninstall via Device Admin — ✅ VERIFIED IN REPO
`android/app/src/main/java/com/lockoutprotocol/guardian/tamper/DeviceOwnerPolicy.kt:45`

```kotlin
runCatching { dpm.setUninstallBlocked(admin, context.packageName, true) }
```

Plus `GuardianAdminReceiver` with `BIND_DEVICE_ADMIN` at `AndroidManifest.xml:102-113`.

📋 **POLICY (RE-CHECK):** Device Admin is restricted to enterprise EMM/DPC and verified parental
control apps. Using it to block uninstall of a *consumer self-control* app is reported to fall
under the Malware / Device and Network Abuse policies — i.e. removal, not just rejection.

**Smallest fix:** remove the `setUninstallBlocked` call, the `GuardianAdminReceiver`, the
`BIND_DEVICE_ADMIN` receiver block, and `res/xml/device_admin.xml`.

**What this costs:** this is a real capability loss, and it is worth being honest about it.
`SAFEGUARDS.md` treats tamper-resistance as core. But note the repo's own README already concedes
*"A determined technical owner can defeat it… This is friction plus a witness, not a prison."*
The **witness** — the ntfy alert to the accountability partner — survives intact, and the
Cloudflare heartbeat watchdog (`android/server/cloudflare-worker`) already covers the uninstall
case *without* Device Admin, by alerting the partner when check-ins stop. That is the compliant
version of the same guarantee, and it already exists in this repo.

> **Decision needed from Shaya:** Play-compliant build (no Device Admin) vs. the current
> full-strength build. These can coexist — see §C.

### A2. No `isMonitoringTool` declaration, and the framing is wrong — ✅ VERIFIED MISSING
No `isMonitoringTool` meta-data anywhere in the manifest.

📋 **POLICY (RE-CHECK):** monitoring apps are reportedly required to declare
`<meta-data android:name="isMonitoringTool" android:value="…"/>`, show a persistent notification,
and disclose monitoring in the store listing. The policy is also reported to say you may *not*
monitor an adult even with consent unless you are an enterprise solution.

**This is a positioning problem, and it is the subtle one.** The current README leads with
*"blocks the app and notifies your accountability partner"* and *"makes itself hard to quietly
switch off."* Read cold by a reviewer, that scans as partner-surveillance software.

The honest and accurate reframing — which is also what the app actually is — is:
**a personal digital wellbeing tool that the device owner installs on their own device, which
lets them voluntarily share their own activity with a person they choose.** The owner is the
subject, not the target. That distinction has to be visible in the store listing, the first-run
screen, and the app title/description, not just be true.

**Smallest fix:** rewrite the store listing and first-run copy around self-control; keep the
persistent foreground-service notification (already present via `MonitorService`); resolve which
`isMonitoringTool` value applies, if any, given the app is not child-monitoring or enterprise —
**this specific question needs a direct read of the current policy page and may need a Play
Console policy support ticket.** It is the single biggest open question in this document.

### A3. Screen capture uploaded to a third party, with no disclosure — ✅ VERIFIED
`canTakeScreenshot="true"` + `canRetrieveWindowContent="true"` in
`res/xml/accessibility_config.xml`, and images go to Ollama Cloud. **No privacy policy exists
anywhere in this repo** (`README.md`, `SAFEGUARDS.md`, `LICENSE` only).

📋 **POLICY (RE-CHECK):** a prominent in-app disclosure must appear *before* the permission
request, must be in the app itself (not only the listing or privacy policy), and must state what
is collected and where it goes.

**Smallest fix:**
1. Write a privacy policy and host it at a public HTTPS URL (GitHub Pages is fine and free). It
   must say: screenshots of user-selected apps are captured, transmitted over HTTPS to Ollama
   Cloud for classification, and state the retention/deletion position.
2. Add a full-screen disclosure in `SetupActivity` *before* the accessibility prompt: "Guardian
   will take pictures of the screen in the apps you choose and send them to Ollama's servers to
   check them against your rules." with explicit Accept/Decline.
3. Fill the Data Safety form to match exactly.

### A4. `QUERY_ALL_PACKAGES` — ✅ VERIFIED IN REPO
`AndroidManifest.xml:13`.

📋 **POLICY (RE-CHECK):** reported to be denied where a narrower mechanism suffices. A
"watch the apps you choose" app almost certainly has a narrower mechanism.

**Smallest fix** — drop the permission, add:
```xml
<queries>
    <intent>
        <action android:name="android.intent.action.MAIN" />
        <category android:name="android.intent.category.LAUNCHER" />
    </intent>
</queries>
```
This still enumerates every launchable app, which is all the watchlist picker needs. This one is
cheap, low-risk, and worth doing regardless of the other decisions.

⚠️ Check first whether the auto-enrol-new-apps feature depends on broader visibility — if it does,
that feature needs rework too.

### A5. `targetSdk = 34` — ✅ VERIFIED IN REPO
`android/app/build.gradle.kts:13` (`compileSdk = 34`, `targetSdk = 34`, `minSdk = 34`).

📋 **POLICY (RE-CHECK — this is the one most likely to be stale):** Play enforces a rolling annual
target-API requirement. The research pass **inferred** that new submissions in 2026 need API 36,
extrapolating from the cadence; it did not confirm it. **Read
<https://support.google.com/googleplay/android-developer/answer/11926878> and take the number
from there.**

**Smallest fix:** bump `compileSdk`/`targetSdk` to whatever that page says, then fix what breaks.
Expect breakage around the foreground-service and overlay behaviour.

Also note `minSdk = 34` excludes every device below Android 14 — a large share of the market and
most of the target audience's hardware. Nothing forces `minSdk` that high; lowering it is a
separate, worthwhile task.

### A6. No release signing config, no AAB — ✅ VERIFIED IN REPO
`build.gradle.kts` has a `release` block with no `signingConfigs`. README confirms: *"there are
no signed release builds."*

**Smallest fix:** generate an upload keystore, add `signingConfigs`, keep the keystore and its
passwords **out of git** (`gradle.properties` in `~/.gradle`, never the repo), enrol in Play App
Signing, build an `.aab`.

> ⚠️ From prior experience on this machine (Quran Together / crowdsource-translation): verify the
> artifact is really release-signed with
> `keytool -printcert -jarfile app-release.aab` before believing it. A debug-signed bundle at the
> expected path has silently happened here before. Also: `aapt2` cannot read `.aab` — use
> `bundletool`.

### A7. Account-level gates — 📋 POLICY (RE-CHECK)
Reported requirements for a first release from a personal developer account:
- Identity verification (government ID + address).
- **12 opt-in testers, 14 continuous days of closed testing** before production access.
- Data Safety form, public privacy policy URL, IARC content rating, target audience (18+).
- **App Access credentials for reviewers** — this app is behind a passcode, so the reviewer
  cannot get in without one. Easy to overlook and an automatic rejection.

**The 12-tester/14-day gate is the long pole.** If it applies, it is a two-week minimum wall
clock *after* everything else is done. **Check whether it applies to this account, today**, and if
so start recruiting 12 testers in parallel with the code work — the marketing todos already in
`projects/memory/lockout-protocol.md` (Reddit, Discord, school friends) are exactly the tester
pipeline. That reordering is the single highest-value scheduling change available.

---

## B. iOS — feasibility

**The vision-classification design does not port. This is a hard architectural limit, not a
policy one.**

📋 iOS sandboxes display memory; no third-party app can capture another app's screen contents.
`ReplayKit` needs per-session consent and shows a recording banner. So *"screenshot the foreground
app and ask a vision model about it"* — the entire premise — **cannot exist on iOS.**

What an iOS version can be, via the Screen Time API suite:

| Android feature | iOS | Status |
|---|---|---|
| Foreground app detection | `FamilyControls` opaque `ApplicationToken` | Adapted — tokens only; the app never learns *which* app it is |
| Block overlay | `ManagedSettings` / `ManagedSettingsUI` shield | Adapted — system shield, customisable text |
| Usage schedules & limits | `DeviceActivity` monitor extension | Adapted |
| **Vision classification of screen content** | — | **DROPPED** |
| **Anti-uninstall** | — | **DROPPED** |
| **Kill background processes** | — | **DROPPED** |

So the iOS app is a **different product**: block-by-app-and-schedule, with a partner alert. No AI.
That is a legitimate and useful app, but it is not this app, and the roadmap should say so
explicitly rather than carrying "port to iOS" as if it were a port.

**Gate:** `com.apple.developer.family-controls` is request-gated by Apple
(<https://developer.apple.com/contact/request/family-controls>), reportedly 1–3 weeks turnaround,
needed for the main bundle ID *and* every extension. Apple Developer Program is $99/yr.

**Recommendation:** submit the FamilyControls entitlement request **now**, before writing any iOS
code. It is free, it costs one form, and the 1–3 week wait runs in parallel with the Android work.
If it is refused, the whole iOS track is dead and it is much better to learn that now.

---

## C. Suggested sequencing

The cheap, no-regret items first; the irreversible product decision last.

**This week, no code decisions needed:**
1. Submit the Apple FamilyControls entitlement request (starts a 1–3 week clock).
2. Confirm the **current** target-SDK number from Google's page.
3. Confirm whether the 12-tester / 14-day rule applies to this account; if yes, start recruiting.
4. Write the privacy policy, publish on GitHub Pages.
5. Create the upload keystore; get a signed `.aab` building (nothing else can be tested until an
   artifact exists).

**Then, low-risk code:**
6. `QUERY_ALL_PACKAGES` → `<queries>`.
7. Bump `compileSdk`/`targetSdk`; fix fallout.
8. Add the pre-permission prominent disclosure screen.
9. Record the accessibility-use demo video (needed for the declaration form).

**Then the actual decision:**
10. **Fork the tamper layer behind a build flavour.** `playRelease` drops Device Admin and
    anti-uninstall; `sideloadRelease` keeps everything. Same codebase, one `if`. The Play build is
    compliant; the full-strength build stays available as a direct APK download from GitHub, which
    is how it is distributed today anyway. **This is the recommendation** — it avoids trading away
    the app's actual purpose for store access, and costs one product flavour.

---

## D. Open questions for Shaya

1. **Device Admin:** accept the build-flavour split (§C10), or keep full strength and skip Play
   entirely (GitHub APK + F-Droid)? F-Droid has none of these restrictions and its audience
   overlaps heavily with this app's.
2. **Is a Google Play developer account already registered and identity-verified?** ($25 one-time.)
   If not, that is step zero and it gates the 14-day test clock.
3. **Is there an Apple Developer account?** ($99/yr, needed before the entitlement request.)
4. Does the auto-enrol-new-apps feature depend on `QUERY_ALL_PACKAGES` (blocks A4)?
5. iOS: accept that it becomes a no-AI, block-by-schedule app — or drop the iOS track?

---

## E. Not verified

Every 📋 item. In particular the 2026 target-SDK number was explicitly inferred, not read. The
`isMonitoringTool` value question (§A2) has no confident answer here and may need a Play Console
policy ticket. Do not treat this file as a compliance sign-off.
