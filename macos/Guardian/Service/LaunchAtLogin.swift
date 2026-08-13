import Foundation
import ServiceManagement

/// Persistence: registers Guardian as a login item so quitting or killing it isn't a lasting bypass —
/// it comes back at the next login. This is the sanctioned macOS API (SMAppService, macOS 13+).
///
/// For *immediate* relaunch-on-quit (not just at login), [KeepAliveAgent] ships a KeepAlive
/// LaunchAgent in Contents/Library/LaunchAgents and registers it with `SMAppService.agent(...)`.
/// [Persistence] below reconciles the two so they never double-launch.
@MainActor
enum LaunchAtLogin {

    static func apply(_ enabled: Bool) {
        guard #available(macOS 13.0, *) else { return }
        do {
            switch (enabled, SMAppService.mainApp.status) {
            case (true, let s) where s != .enabled:
                try SMAppService.mainApp.register()
                EventLog.shared.add("🔒 Guardian registered to launch at login")
            case (false, .enabled):
                try SMAppService.mainApp.unregister()
            default:
                break
            }
        } catch {
            EventLog.shared.add("⚠️ login-item update failed: \(error.localizedDescription)")
        }
    }

    static var isEnabled: Bool {
        guard #available(macOS 13.0, *) else { return false }
        return SMAppService.mainApp.status == .enabled
    }
}

/// Reconciles the two persistence mechanisms so they never fight. The KeepAlive agent already covers
/// login *and* immediate relaunch, so when it's on we drop the plain login item to avoid launching
/// Guardian twice. Call this on launch and whenever either toggle changes.
@MainActor
enum Persistence {
    static func apply() {
        let prefs = Prefs.shared
        if prefs.keepAlive {
            KeepAliveAgent.apply(true)
            LaunchAtLogin.apply(false)          // agent supersedes the plain login item
        } else {
            KeepAliveAgent.apply(false)
            LaunchAtLogin.apply(prefs.relaunchAtLogin)
        }
    }
}
