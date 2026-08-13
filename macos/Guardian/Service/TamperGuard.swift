import CoreGraphics
import Foundation

/// Watches for the macOS ways Guardian gets defeated and reacts, mirroring the Android tamper layer:
///
///  1. **Screen Recording permission revoked** — Guardian's only capture path. If it was granted and
///     is now gone while monitoring is enabled, fire a tamper alert (the analogue of Android's
///     "accessibility turned off" detection).
///  2. **Monitor watchdog** — if monitoring should be running but the loop died, restart it.
///
/// A user with admin rights can always revoke a TCC permission or force-quit the app; this can't
/// prevent that, but it makes it loud and self-healing instead of a silent bypass.
@MainActor
final class TamperGuard {

    static let shared = TamperGuard()

    private var timer: Timer?
    private let prefs = Prefs.shared

    /// Consecutive "permission looks gone" readings taken while the screen was visible. Debounced so
    /// a single ScreenCaptureKit hiccup doesn't read as a revoke.
    private var missedGrantChecks = 0

    private init() {}

    func start() {
        guard timer == nil else { return }
        // Seed the baseline immediately, then poll.
        Task { await check() }
        timer = Timer.scheduledTimer(withTimeInterval: 15, repeats: true) { [weak self] _ in
            Task { @MainActor in await self?.check() }
        }
    }

    func stop() { timer?.invalidate(); timer = nil }

    private func check() async {
        // 1. Screen Recording (TCC) transition tracking.
        //    Only meaningful while the screen is actually on: with the display asleep or the session
        //    locked, SCShareableContent reports no displays, which looks exactly like a revoked
        //    permission. That false positive is why an alert fired every time the screen went off.
        if ScreenState.isVisible {
            let granted = await ScreenCapturer.hasPermission()
            if prefs.monitoringEnabled {
                if prefs.screenRecordingGranted && !granted {
                    // Require two consecutive misses so a momentary ScreenCaptureKit hiccup can't
                    // masquerade as tampering. A real revoke persists and alerts 15s later.
                    missedGrantChecks += 1
                    if missedGrantChecks >= 2 {
                        prefs.screenRecordingGranted = false
                        missedGrantChecks = 0
                        TamperAlert.raise(
                            "Guardian's Screen Recording permission was turned off — it can no longer see the screen.",
                            force: true)
                    }
                } else if granted {
                    missedGrantChecks = 0
                    if !prefs.screenRecordingGranted { prefs.screenRecordingGranted = true }
                }
            } else if granted {
                prefs.screenRecordingGranted = true
            }
        } else {
            // Screen is off/locked — the reading is meaningless, so don't hold a miss against it.
            missedGrantChecks = 0
        }

        // 2. Watchdog: keep the monitor alive.
        if prefs.monitoringEnabled && !MonitorService.shared.isRunning {
            EventLog.shared.add("🔄 watchdog restarting monitor")
            MonitorService.shared.start()
        }
    }
}
