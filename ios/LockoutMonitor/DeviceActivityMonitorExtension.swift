import DeviceActivity
import Foundation
import ManagedSettings

/// Lifts the shield when the session's time is up, even if the app is never opened again.
///
/// Without this, "90 minutes" would mean "90 minutes, and then until you next open Lockout".
/// Same constraints as the shield extensions: own process, no UI, launched cold.
class DeviceActivityMonitorExtension: DeviceActivityMonitor {

    private static let storeName =
        ManagedSettingsStore.Name("com.lockoutprotocol.lockout.focus")

    override func intervalDidEnd(for activity: DeviceActivityName) {
        super.intervalDidEnd(for: activity)
        endSession(reason: "time's up")
    }

    /// No usage-threshold events are registered yet.
    override func eventDidReachThreshold(_ event: DeviceActivityEvent.Name,
                                        activity: DeviceActivityName) {
        super.eventDidReachThreshold(event, activity: activity)
        // A no-op rather than unimplemented, so adding an event later can't silently do nothing.
    }

    // MARK: - Ending

    private func endSession(reason: String) {
        // Lift the shield first and unconditionally: it must happen even if the rest fails.
        let store = ManagedSettingsStore(named: Self.storeName)
        store.shield.applications = nil
        store.shield.applicationCategories = nil

        // Then archive it, so the app agrees the session is over next launch.
        let dir = containerDirectory()
        let sessionURL = dir.appendingPathComponent("focus_session.json")
        guard let data = try? Data(contentsOf: sessionURL),
              var session = try? JSONDecoder().decode(FocusSession.self, from: data) else {
            try? FileManager.default.removeItem(at: sessionURL)
            return
        }
        session.endedAt = Date()
        session.endedReason = reason

        if var encoded = try? JSONEncoder().encode(session) {
            encoded.append(0x0A)
            let historyURL = dir.appendingPathComponent("focus_history.jsonl")
            if let handle = try? FileHandle(forWritingTo: historyURL) {
                defer { try? handle.close() }
                try? handle.seekToEnd()
                try? handle.write(contentsOf: encoded)
            } else {
                try? encoded.write(to: historyURL, options: .atomic)
            }
        }
        try? FileManager.default.removeItem(at: sessionURL)
    }

    /// Duplicated from `SessionStore` rather than shared: importing it would pull `@MainActor`
    /// and `ObservableObject` into a process with a few megabytes to spend. The App Group id is
    /// the one thing that must stay in step, and `tools/check_ios.py` asserts it.
    private func containerDirectory() -> URL {
        FileManager.default.containerURL(
            forSecurityApplicationGroupIdentifier: "group.com.lockoutprotocol.lockout")
            ?? FileManager.default.temporaryDirectory
    }
}
