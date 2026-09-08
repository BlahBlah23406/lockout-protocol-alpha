import DeviceActivity
import Foundation
import ManagedSettings

/// Lifts the shield when the session's time is up, even if the app is never opened again.
///
/// This is what makes a timed session trustworthy. Without it, "90 minutes" would really mean
/// "90 minutes, and then until you next open Lockout" — and a shield that outlives its session is
/// exactly the kind of thing that gets a focus app deleted in irritation. iOS launches this
/// extension at the scheduled interval end whether or not the app is running.
///
/// Same constraints as the shield extensions: own process, no UI, a few megabytes, launched cold.
/// It does two file operations and clears a settings store.
class DeviceActivityMonitorExtension: DeviceActivityMonitor {

    private static let storeName =
        ManagedSettingsStore.Name("com.lockoutprotocol.lockout.focus")

    override func intervalDidEnd(for activity: DeviceActivityName) {
        super.intervalDidEnd(for: activity)
        endSession(reason: "time's up")
    }

    /// A session can also be ended by the schedule being replaced. Clearing on `intervalDidStart`
    /// would be wrong (that is when a session *begins*), so only the end and the warning points
    /// are handled.
    override func eventDidReachThreshold(_ event: DeviceActivityEvent.Name,
                                        activity: DeviceActivityName) {
        super.eventDidReachThreshold(event, activity: activity)
        // No usage-threshold events are registered yet. Implemented as a no-op rather than left
        // unimplemented so that adding one later can't silently do nothing.
    }

    // MARK: - Ending

    private func endSession(reason: String) {
        // 1. Lift the shield. This is the part that must happen even if everything else fails, so
        //    it goes first and unconditionally.
        let store = ManagedSettingsStore(named: Self.storeName)
        store.shield.applications = nil
        store.shield.applicationCategories = nil

        // 2. Archive the session and remove it, so the app agrees the session is over next launch.
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

    /// Duplicated from `SessionStore` rather than shared, deliberately: pulling the app's session
    /// store into this target would pull in `@MainActor`, `ObservableObject`, and everything they
    /// reference, into a process with a few megabytes to spend. The App Group id is the one thing
    /// that must stay in step, and it is asserted by the app's own diagnosis screen.
    private func containerDirectory() -> URL {
        FileManager.default.containerURL(
            forSecurityApplicationGroupIdentifier: "group.com.lockoutprotocol.lockout")
            ?? FileManager.default.temporaryDirectory
    }
}
