import AppKit
import CoreGraphics
import Foundation
import UserNotifications

/// The always-on heart of Guardian. Runs a response-driven loop: when a monitored app is frontmost
/// it grabs a screenshot (via ScreenCaptureKit — one frame, no recording), classifies it with the
/// Ollama vision model, and enforces hides/quits + push alerts. Direct port of the Android
/// `MonitorService`.
@MainActor
final class MonitorService: ObservableObject {

    static let shared = MonitorService()

    @Published private(set) var isRunning = false
    /// Short status line for the dashboard.
    @Published private(set) var status = "Idle"

    private var task: Task<Void, Never>?
    private let prefs = Prefs.shared
    private let log = EventLog.shared

    /// Per-bundle throttle so persistently-unverifiable apps don't spam the alert.
    private var lastAlertAt: [String: Date] = [:]

    /// Tracks display sleep/lock transitions so the pause is logged once, not every tick.
    private var screenWasVisible = true

    // Cadence (mirrors Android): a small floor between back-to-back checks while on a monitored
    // app, and a lazier poll when nothing monitored is on screen.
    private let minGap: UInt64 = 1_200_000_000      // 1.2s
    private let idlePoll: UInt64 = 2_500_000_000     // 2.5s
    private let alertThrottle: TimeInterval = 10 * 60 // 10 min

    private init() {}

    func start() {
        guard task == nil else { return }
        isRunning = true
        prefs.monitoringEnabled = true
        status = "Monitoring active"
        log.add("▶︎ monitoring started\(prefs.dryRun ? " [TEST]" : "")")
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
            let active = await tick()
            try? await Task.sleep(nanoseconds: active ? minGap : idlePoll)
        }
    }

    /// Returns true if a monitored app was on screen and was actually checked.
    private func tick() async -> Bool {
        // A block overlay is up — the screen is already covered by us; don't capture/evaluate.
        if BlockController.shared.isBlocking { return false }

        // Display asleep / locked / screen saver: nobody can be looking at anything, and capturing
        // would just hand us a black frame that reads as "can't see" and alerts. Pause instead.
        guard ScreenState.isVisible else {
            if screenWasVisible {
                screenWasVisible = false
                log.add("💤 screen \(ScreenState.reason) — monitoring paused")
                status = "Screen \(ScreenState.reason)"
            }
            return false
        }
        if !screenWasVisible {
            screenWasVisible = true
            log.add("👁️ screen back on — monitoring resumed")
            status = "Monitoring active"
        }

        let monitored = prefs.monitoredApps
        guard let fg = FrontmostApp.bundleId, !fg.isEmpty, monitored.contains(fg) else {
            return false
        }

        // User dismissed a block for this app recently — leave it alone until the override expires.
        if Overrides.isActive(fg) { return false }

        let dry = prefs.dryRun
        let name = FrontmostApp.shortName(for: fg)

        // Grab a screenshot of the display.
        let capStart = Date()
        let frame = await ScreenCapturer.capture()
        let capMs = Int(Date().timeIntervalSince(capStart) * 1000)
        log.add("📷 screenshot \(name) (\(capMs)ms capture)\(dry ? " [TEST]" : "")")
        status = "Checking \(name)…"

        // 1. Couldn't capture at all -> can't verify (safe handling). Core monitoring can't see the
        //    screen — that's a MAIN-monitoring event, so it notifies.
        guard let frame else {
            await handleUnverifiable(fg, name, "screen could not be captured (grant Screen Recording?)", dry)
            return true
        }

        // 2. Captured but blank/uniform -> protected/blank -> can't verify (notifies, as above).
        if FrameQuality.isUnreadable(frame) {
            await handleUnverifiable(fg, name, "screen is blank or capture-protected", dry)
            return true
        }

        // 3. Ask the AI.
        let aiStart = Date()
        let mainCfg = OllamaClient(prefs: prefs).config()
        let mainVerdict = await OllamaClient(prefs: prefs).evaluate(frame, config: mainCfg)
        let mainMs = Int(Date().timeIntervalSince(aiStart) * 1000)

        if mainVerdict.violation {
            if dry {
                log.add("🟠 \(name) WOULD BLOCK (\(mainMs)ms) — \(mainVerdict.reason) [TEST]")
                status = "WOULD block \(name)"
            } else {
                log.add("🚫 \(name) VIOLATION (\(mainMs)ms) — \(mainVerdict.reason)")
                await enforceViolation(fg, name, mainVerdict.reason)
            }
            return true
        }
        if mainVerdict.transient {
            // Transient backend hiccup (HTTP 503/429/5xx, timeout): the AI is busy, NOT the user
            // hiding anything — so we NEVER hide/quit here. Log and move on; the next tick retries.
            log.add("⏳ \(name) AI busy — skipped (\(mainMs)ms) — \(mainVerdict.reason)")
            status = "AI busy — skipped \(name)"
            return true
        }
        if mainVerdict.undetermined {
            await handleUnverifiable(fg, name, "AI could not analyse (\(mainVerdict.reason))", dry)
            return true
        }

        log.add("✅ \(name) cleared (\(mainMs)ms, \(mainCfg.model))")
        status = "Cleared \(name)"
        return true
    }

    // MARK: - Enforcement

    /// Confirmed guideline violation: raise the full-screen block overlay (dismiss/override with the
    /// passcode) + push alert. Mirrors the Android BlockActivity enforce path.
    private func enforceViolation(_ bundleId: String, _ name: String, _ reason: String) async {
        prefs.lastViolationAt = Date()
        status = "BLOCKED \(name)"
        BlockController.shared.show(bundleId: bundleId, appName: name, reason: reason)
        notifyLocal("Guardian blocked \(name)", reason)
        await sendAlert(bundleId, "[Guardian] Blocked \(name)",
                        "Guardian blocked the screen in \(name).\n\nReason: \(reason)", throttle: false)
    }

    /// A monitored app's screen could NOT be verified (blank/protected frame, capture failure, or
    /// AI unreachable). Never quits unless the user opted in. Logs + pushes (throttled).
    private func handleUnverifiable(_ bundleId: String, _ name: String, _ why: String, _ dry: Bool) async {
        if dry {
            log.add("🙈 \(name) CAN'T SEE — \(why) — would alert [TEST]")
            status = "Can't see \(name)"
            return
        }
        log.add("🙈 \(name) CAN'T SEE — \(why)")
        status = "Can't see \(name)"
        if prefs.alertOnUnverifiable {
            await sendAlert(bundleId, "[Guardian] Couldn't verify \(name)",
                            "Guardian could not see what was on screen in \(name) (\(why)).",
                            throttle: true)
        }
        if prefs.closeUnverifiable {
            FrontmostApp.hide(bundleId: bundleId)
        }
    }

    private func sendAlert(_ bundleId: String, _ title: String, _ body: String, throttle: Bool) async {
        if throttle {
            if let last = lastAlertAt[bundleId], Date().timeIntervalSince(last) < alertThrottle { return }
            lastAlertAt[bundleId] = Date()
        }
        let fullBody = "\(body)\n\n\(Date())"
        let cfg = Pusher.Config(enabled: prefs.pushEnabled, server: prefs.ntfyServer, topic: prefs.ntfyTopic)
        let result = await Pusher.send(cfg, title: title, message: fullBody)
        if case .failure(let e) = result {
            log.add("⚠️ push failed: \(e.localizedDescription)")
        }
    }

    /// Local macOS notification (the analogue of the on-device toast/notification).
    private func notifyLocal(_ title: String, _ body: String) {
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        let req = UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil)
        UNUserNotificationCenter.current().add(req)
    }
}
