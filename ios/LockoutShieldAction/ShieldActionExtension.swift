import Foundation
import ManagedSettings

/// What the two shield buttons do, and where the accountability levels differ on iOS.
///
/// This runs in its own process and cannot show UI, so it cannot ask for a passcode: a locked
/// session's unshield defers and the shield text points the user at the app. Being upfront about
/// that is better than pretending the button worked.
///
/// "Back to work" is the primary action, because going back to work should be the path of least
/// resistance.
class ShieldActionExtension: ShieldActionDelegate {

    override func handle(action: ShieldAction, for application: ApplicationToken,
                         completionHandler: @escaping (ShieldActionResponse) -> Void) {
        completionHandler(respond(to: action, token: application))
    }

    override func handle(action: ShieldAction, for webDomain: WebDomainToken,
                         completionHandler: @escaping (ShieldActionResponse) -> Void) {
        // No per-app unshield here: there is no "let this one through" that doesn't reopen the
        // whole category.
        switch action {
        case .primaryButtonPressed:
            completionHandler(.close)
        default:
            recordUnshieldAttempt()
            completionHandler(.defer)
        }
    }

    override func handle(action: ShieldAction, for category: ActivityCategoryToken,
                         completionHandler: @escaping (ShieldActionResponse) -> Void) {
        switch action {
        case .primaryButtonPressed:
            completionHandler(.close)
        default:
            recordUnshieldAttempt()
            completionHandler(.defer)
        }
    }

    // MARK: - The decision

    private func respond(to action: ShieldAction, token: ApplicationToken) -> ShieldActionResponse {
        guard let session = SharedSession.current() else {
            // No live session: the shield is stale.
            lift(token: token)
            return .none
        }

        switch action {
        case .primaryButtonPressed:
            return .close                       // back to work; shield stays up

        case .secondaryButtonPressed:
            if session.accountability.requiresPasscodeToEnd {
                // An extension cannot ask for a passcode. `.defer` keeps the shield up; the
                // shield's own text tells them to open Lockout. Faking success would leave an
                // unshielded app on a session the partner believes is locked.
                recordUnshieldAttempt()
                return .defer
            }
            // Self-managed: the interruption was the friction, and it has been paid.
            lift(token: token)
            recordUnshield(session: session)
            return .none

        @unknown default:
            return .close
        }
    }

    /// Remove just this app's shield. The named store means this never touches a parent's Screen
    /// Time rules.
    private func lift(token: ApplicationToken) {
        let store = ManagedSettingsStore(
            named: ManagedSettingsStore.Name("com.lockoutprotocol.lockout.focus"))
        var current = store.shield.applications ?? []
        current.remove(token)
        store.shield.applications = current.isEmpty ? nil : current
    }

    // MARK: - Recording
    //
    // The extension can't touch `SessionStore` and shouldn't spend its memory budget on the
    // judgement log, so it spools one line and the app folds it in on next launch.

    private func recordUnshield(session: FocusSession) {
        appendSpool(["event": "unshield", "session_id": session.id,
                     "ts": Date().timeIntervalSince1970])
    }

    private func recordUnshieldAttempt() {
        appendSpool(["event": "unshield_blocked", "ts": Date().timeIntervalSince1970])
    }

    private func appendSpool(_ row: [String: Any]) {
        let url = SessionStore.containerDirectory()
            .appendingPathComponent("shield_spool.jsonl")
        guard var data = try? JSONSerialization.data(withJSONObject: row) else { return }
        data.append(0x0A)
        if let handle = try? FileHandle(forWritingTo: url) {
            defer { try? handle.close() }
            try? handle.seekToEnd()
            try? handle.write(contentsOf: data)
        } else {
            try? data.write(to: url, options: .atomic)
        }
    }
}
