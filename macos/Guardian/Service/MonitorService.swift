import AppKit
import CoreGraphics
import Foundation
import UserNotifications

/// The monitoring loop. Two modes meet here:
///
/// **Focus mode** (the product). A session is running — the user declared a task like "revising
/// integration by parts" — so every `intervalSeconds` we capture one frame of whichever watched app
/// is frontmost and ask the model whether that screen belongs to that task.
///
/// **Content rules** (opt-in, off by default). The original behaviour: an always-on classifier
/// checking screens against written content guidelines. Kept because it works, but it is no longer
/// what the app is for.
///
/// The most important structural change: **when no session is running, nothing is captured at
/// all** — not captured and discarded, never taken. A monitor that only looks during a window you
/// opened yourself is a different thing to live with, and that difference is worth the extra branch.
///
/// Cadence follows the session's interval rather than how fast the model answers. The old loop
/// fired 1.2s after each reply, which is right for content safety (one frame of the wrong thing
/// matters) and wrong here: it would burn hundreds of calls an hour on a question whose answer
/// changes over minutes.
@MainActor
final class MonitorService: ObservableObject {

    static let shared = MonitorService()

    @Published private(set) var isRunning = false
    /// Short status line for the dashboard and the menu bar.
    @Published private(set) var status = "Idle"

    private var task: Task<Void, Never>?
    private let prefs = Prefs.shared
    private let log = EventLog.shared
    private let sessions = SessionStore.shared

    /// Per-bundle throttle so persistently-unverifiable apps don't spam the alert.
    private var lastAlertAt: [String: Date] = [:]
    private var screenWasVisible = true
    /// When the next focus check is due, per app. Keyed by app so switching apps checks the new one
    /// promptly instead of inheriting the previous app's countdown — the moment you switch into a
    /// distraction is exactly the moment worth looking.
    private var nextCheckAt: [String: Date] = [:]

    // Content-rules cadence (unchanged from the original app).
    private let minGap: TimeInterval = 1.2
    private let idlePoll: TimeInterval = 2.5
    /// How often we re-check *which* app is frontmost while not on a watched app. Cheap — one
    /// AppKit call, no capture, no inference — so it can be brisk.
    private let focusIdlePoll: TimeInterval = 3.0
    /// After a transient backend failure, retry sooner than a full interval but not instantly.
    private let transientRetry: TimeInterval = 20
    private let alertThrottle: TimeInterval = 10 * 60

    private init() {}

    // MARK: - Lifecycle

    func start() {
        guard task == nil else { return }
        isRunning = true
        prefs.monitoringEnabled = true
        status = "Monitoring active"
        let mode = sessions.isActive ? "focus" : "content-rules"
        log.add("▶︎ monitoring started (\(mode))\(prefs.dryRun ? " [TEST]" : "")")
        nextCheckAt.removeAll()
        task = Task { await loop() }
    }

    func stop() {
        task?.cancel()
        task = nil
        isRunning = false
        prefs.monitoringEnabled = false
        status = "Stopped"
        log.add("■ monitoring stopped")
    }

    private func loop() async {
        while !Task.isCancelled {
            let wait = await tick()
            try? await Task.sleep(nanoseconds: UInt64(max(wait, 0.5) * 1_000_000_000))
        }
    }

    // MARK: - One tick

    /// Do at most one unit of work. Returns how many seconds to wait before the next tick.
    private func tick() async -> TimeInterval {
        // A block overlay is up — we already cover the screen; don't capture or evaluate.
        if BlockController.shared.isBlocking { return idlePoll }

        // Display asleep / locked / screen saver: nobody is looking at anything, and capturing
        // would hand us a black frame that reads as "can't see" and alerts. Pause instead.
        guard ScreenState.isVisible else {
            if screenWasVisible {
                screenWasVisible = false
                log.add("💤 screen \(ScreenState.reason) — monitoring paused")
                status = "Screen \(ScreenState.reason)"
            }
            return idlePoll
        }
        if !screenWasVisible {
            screenWasVisible = true
            log.add("👁️ screen back on — monitoring resumed")
            status = "Monitoring active"
        }

        if let session = sessions.current {
            return await focusTick(session)
        }
        if prefs.contentRulesEnabled {
            return await contentTick() ? minGap : idlePoll
        }

        // Nothing to do: no session, content rules off. Explicitly *not* capturing anything.
        status = "No focus session — not watching"
        return idlePoll
    }

    // MARK: - Focus mode

    private func focusTick(_ session: FocusSession) async -> TimeInterval {
        let interval = TimeInterval(session.intervalSeconds)

        if session.isPaused, let until = session.pausedUntil {
            let left = max(until.timeIntervalSinceNow, 0)
            status = "Paused \(Int(left))s"
            return min(left + 0.5, interval)
        }

        let watchlist = session.watchlist(defaults: prefs.monitoredApps)
        guard let fg = FrontmostApp.bundleId, !fg.isEmpty, watchlist.contains(fg) else {
            // Not a watched app. In focus mode this is the normal, uninteresting case — you are in
            // your editor, or your terminal, or anything you never asked to be policed.
            status = idleStatus(session)
            return focusIdlePoll
        }

        if Overrides.isActive(fg) { return focusIdlePoll }

        // Rate-limit per app so switching back and forth can't force a check storm.
        if let due = nextCheckAt[fg], due > Date() {
            status = idleStatus(session)
            return min(due.timeIntervalSinceNow, focusIdlePoll)
        }

        let name = FrontmostApp.shortName(for: fg)
        let title = FrontmostApp.windowTitle(for: fg)
        let dry = prefs.dryRun

        guard let frame = await ScreenCapturer.capture() else {
            await handleUnverifiable(fg, name, "screen could not be captured (grant Screen Recording?)", dry)
            nextCheckAt[fg] = Date().addingTimeInterval(interval)
            return interval
        }
        if FrameQuality.isUnreadable(frame) {
            await handleUnverifiable(fg, name, "screen is blank or capture-protected", dry)
            nextCheckAt[fg] = Date().addingTimeInterval(interval)
            return interval
        }

        status = "Checking \(name)…"
        let cfg = prefs.providerConfig()
        let notes = extraNotes(for: session, app: fg)
        let started = Date()
        let verdict = await Providers.evaluate(cfg, image: frame, task: session.task,
                                               appName: name, windowTitle: title,
                                               extraNotes: notes,
                                               onKeyWorked: { key in
            Task { @MainActor in Prefs.shared.promoteApiKey(key) }
        })
        let ms = Int(Date().timeIntervalSince(started) * 1000)

        // Transient backend trouble is never evidence about the user: log, retry sooner, no block.
        if verdict.transient {
            log.add("⏳ \(name) — AI unavailable (\(verdict.reason)) — skipped")
            status = "AI unavailable — retrying"
            nextCheckAt[fg] = Date().addingTimeInterval(transientRetry)
            return transientRetry
        }

        nextCheckAt[fg] = Date().addingTimeInterval(interval)

        if verdict.undetermined {
            await handleUnverifiable(fg, name, "AI could not analyse (\(verdict.reason))", dry)
            return interval
        }

        if verdict.onTask {
            sessions.recordCheck(offTask: false)
            Judgements.record(session: session, app: fg, appName: name, windowTitle: title,
                              verdict: "on_task", reason: verdict.reason,
                              confidence: verdict.confidence, action: "allowed",
                              provider: cfg.describe)
            log.add("✅ \(name) on task (\(ms)ms, \(cfg.model))")
            status = idleStatus(session)
            return interval
        }

        // Off task.
        sessions.recordCheck(offTask: true)
        let action = dry ? "logged" : "blocked"
        let jid = Judgements.record(session: session, app: fg, appName: name, windowTitle: title,
                                    verdict: "off_task", reason: verdict.reason,
                                    confidence: verdict.confidence, action: action,
                                    provider: cfg.describe)
        if dry {
            log.add("🟠 \(name) WOULD BLOCK — off task (\(ms)ms) — \(verdict.reason) [TEST]")
            status = "WOULD block \(name)"
        } else {
            log.add("🚫 \(name) OFF TASK (\(ms)ms) — \(verdict.reason)")
            await enforceOffTask(session, fg, name, verdict, jid)
        }
        return interval
    }

    private func idleStatus(_ session: FocusSession) -> String {
        guard let remaining = session.remaining else { return "Focus: \(session.task.prefix(40))" }
        return "Focus: \(session.task.prefix(32)) (\(Int(remaining) / 60)m left)"
    }

    /// Standing notes handed to the classifier: the user's own, plus anything the experimental
    /// learner has concluded. Both capped hard — a prompt suffix that grows without bound
    /// eventually costs more than the screenshot does.
    private func extraNotes(for session: FocusSession, app: String) -> String {
        var notes = [prefs.focusNotes.trimmingCharacters(in: .whitespacesAndNewlines)]
        if prefs.learningEnabled {
            notes.append(LearnedPolicy.promptSuffix(task: session.task, app: app))
        }
        return String(notes.filter { !$0.isEmpty }.joined(separator: "\n").prefix(1500))
    }

    /// Raise the block. What the block *offers* depends on the accountability level the session was
    /// started at — read from the session, not from a global setting that could have drifted since.
    private func enforceOffTask(_ session: FocusSession, _ bundleId: String, _ name: String,
                                _ verdict: Providers.Verdict, _ judgementId: String) async {
        prefs.lastViolationAt = Date()
        status = "BLOCKED \(name)"
        BlockController.shared.show(bundleId: bundleId, appName: name, reason: verdict.reason,
                                    session: session, judgementId: judgementId)
        notifyLocal("Off task in \(name)", verdict.reason.isEmpty ? session.task : verdict.reason)

        if session.accountability.alertsPartner {
            await sendAlert(bundleId, "[Lockout] Off task in \(name)",
                            "Task: \(session.task)\n\n\(name) was blocked.\nReason: \(verdict.reason)",
                            throttle: false)
        }
    }

    // MARK: - Content-rules mode (opt-in; the original behaviour)

    /// Returns true if a monitored app was on screen and was actually checked.
    private func contentTick() async -> Bool {
        let monitored = prefs.monitoredApps
        guard let fg = FrontmostApp.bundleId, !fg.isEmpty, monitored.contains(fg) else {
            return false
        }
        if Overrides.isActive(fg) { return false }

        let dry = prefs.dryRun
        let name = FrontmostApp.shortName(for: fg)

        guard let frame = await ScreenCapturer.capture() else {
            await handleUnverifiable(fg, name, "screen could not be captured (grant Screen Recording?)", dry)
            return true
        }
        if FrameQuality.isUnreadable(frame) {
            await handleUnverifiable(fg, name, "screen is blank or capture-protected", dry)
            return true
        }

        let started = Date()
        let cfg = OllamaClient(prefs: prefs).config()
        let verdict = await OllamaClient(prefs: prefs).evaluate(frame, config: cfg)
        let ms = Int(Date().timeIntervalSince(started) * 1000)

        if verdict.violation {
            if dry {
                log.add("🟠 \(name) WOULD BLOCK (\(ms)ms) — \(verdict.reason) [TEST]")
            } else {
                log.add("🚫 \(name) VIOLATION (\(ms)ms) — \(verdict.reason)")
                prefs.lastViolationAt = Date()
                BlockController.shared.show(bundleId: fg, appName: name, reason: verdict.reason)
                notifyLocal("Guardian blocked \(name)", verdict.reason)
                await sendAlert(fg, "[Lockout] Blocked \(name)",
                                "Content rule triggered in \(name).\n\nReason: \(verdict.reason)",
                                throttle: false)
            }
            return true
        }
        if verdict.transient {
            log.add("⏳ \(name) AI busy — skipped (\(ms)ms) — \(verdict.reason)")
            return true
        }
        if verdict.undetermined {
            await handleUnverifiable(fg, name, "AI could not analyse (\(verdict.reason))", dry)
            return true
        }
        log.add("✅ \(name) cleared (\(ms)ms, \(cfg.model))")
        return true
    }

    // MARK: - Shared

    /// A watched app's screen could NOT be read (blank/protected frame, capture failure, or an
    /// answer we couldn't parse). Never blocks. This is the anti-lockout rule: a screen we cannot
    /// see is not a screen we get to punish.
    private func handleUnverifiable(_ bundleId: String, _ name: String, _ why: String,
                                    _ dry: Bool) async {
        if dry {
            log.add("🙈 \(name) CAN'T SEE — \(why) — would alert [TEST]")
            status = "Can't see \(name)"
            return
        }
        log.add("🙈 \(name) CAN'T SEE — \(why)")
        status = "Can't see \(name)"

        let session = sessions.current
        let alerts = prefs.alertOnUnverifiable
            && (session == nil || session!.accountability.alertsPartner)
        if alerts {
            await sendAlert(bundleId, "[Lockout] Couldn't verify \(name)",
                            "Guardian could not see what was on screen in \(name) (\(why)).",
                            throttle: true)
        }
        if prefs.closeUnverifiable { FrontmostApp.hide(bundleId: bundleId) }
    }

    private func sendAlert(_ key: String, _ title: String, _ body: String, throttle: Bool) async {
        if throttle {
            if let last = lastAlertAt[key], Date().timeIntervalSince(last) < alertThrottle { return }
            lastAlertAt[key] = Date()
        }
        let fullBody = "\(body)\n\n\(Date())"
        let cfg = Pusher.Config(enabled: prefs.pushEnabled, server: prefs.ntfyServer,
                                topic: prefs.ntfyTopic)
        let result = await Pusher.send(cfg, title: title, message: fullBody)
        if case .failure(let e) = result {
            log.add("⚠️ push failed: \(e.localizedDescription)")
        }
    }

    private func notifyLocal(_ title: String, _ body: String) {
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        let req = UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil)
        UNUserNotificationCenter.current().add(req)
    }
}
