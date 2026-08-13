import Foundation
import ServiceManagement

/// Immediate relaunch-on-quit persistence, one tier above the plain login item in [LaunchAtLogin].
///
/// It registers a KeepAlive LaunchAgent (bundled at `Contents/Library/LaunchAgents/` and copied in by
/// a build phase). launchd then relaunches Guardian within ~10s of *any* exit — Quit, force-quit, or
/// crash — so stopping the app is no longer a lasting way to defeat monitoring. This is the macOS
/// analogue of the Android boot-receiver + heartbeat watchdog.
///
/// A user with admin rights can still `launchctl bootout` the agent or delete the app; like
/// everything in the tamper layer this raises the cost and noise of a bypass rather than making it
/// impossible. When it's on, the login item is redundant (the agent already covers login), so the
/// caller disables that to avoid a double launch.
@MainActor
enum KeepAliveAgent {

    static let label = "com.lockoutprotocol.guardian.keepalive"
    private static let plistName = "com.lockoutprotocol.guardian.keepalive.plist"

    @available(macOS 13.0, *)
    private static var service: SMAppService { SMAppService.agent(plistName: plistName) }

    static func apply(_ enabled: Bool) {
        guard #available(macOS 13.0, *) else { return }
        do {
            switch (enabled, service.status) {
            case (true, let s) where s != .enabled:
                try service.register()
                EventLog.shared.add("🔒 KeepAlive agent registered — Guardian will relaunch if quit")
            case (false, .enabled):
                try service.unregister()
                EventLog.shared.add("KeepAlive agent removed")
            default:
                break
            }
        } catch {
            EventLog.shared.add("⚠️ KeepAlive agent update failed: \(error.localizedDescription)")
        }
    }

    static var isActive: Bool {
        guard #available(macOS 13.0, *) else { return false }
        return service.status == .enabled
    }
}
