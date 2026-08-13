import Foundation
import UserNotifications

/// One place to raise a "someone is tampering with Guardian" alert. As on Android, the real
/// enforcement is social: the moment a defense is touched, the accountability contact is pushed.
/// Fires an ntfy push + a local macOS notification, de-duped so one tamper action doesn't spam.
@MainActor
enum TamperAlert {

    private static var lastAt: Date?
    private static let dedupe: TimeInterval = 60

    static func raise(_ reason: String, force: Bool = false) {
        if !force, let last = lastAt, Date().timeIntervalSince(last) < dedupe { return }
        lastAt = Date()

        EventLog.shared.add("🛑 TAMPER — \(reason)")

        let prefs = Prefs.shared
        let title = "[Guardian] Tamper alert"
        let host = Host.current().localizedName ?? "this Mac"
        let body = "\(reason)\n\nDevice: \(host)\n\(Date())"

        // Local notification (visible on-screen even if push is down).
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = reason
        UNUserNotificationCenter.current().add(
            UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil))

        // Push to the accountability contact.
        let cfg = Pusher.Config(enabled: prefs.pushEnabled, server: prefs.ntfyServer, topic: prefs.ntfyTopic)
        Task {
            let result = await Pusher.send(cfg, title: title, message: body)
            if case .failure(let e) = result {
                await MainActor.run { EventLog.shared.add("⚠️ tamper push failed: \(e.localizedDescription)") }
            }
        }
    }
}
