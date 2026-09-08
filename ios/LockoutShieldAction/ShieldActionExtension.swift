import Foundation
import ManagedSettings

/// What the two shield buttons do — and therefore where the two accountability levels actually
/// differ on iOS.
///
/// This runs in its own process when a button is tapped. It cannot show UI, so it cannot ask for a
/// passcode: a locked session's "Unshield" therefore does the only honest thing available, which
/// is to hand the user to the app where a passcode *can* be asked for. That is a real limitation
/// of the platform and it is handled by being upfront rather than by pretending the button worked.
///
/// The primary button ("Back to work") just closes — `.close` returns the user to where they came
/// from and leaves the shield up. It is deliberately the primary action: going back to work should
/// be the path of least resistance, not the override.
class ShieldActionExtension: ShieldActionDelegate {

    override func handle(action: ShieldAction, for application: ApplicationToken,
                         completionHandler: @escaping (ShieldActionResponse) -> Void) {
        completionHandler(respond(to: action, token: application))
    }

    override func handle(action: ShieldAction, for webDomain: WebDomainToken,
                         completionHandler: @escaping (ShieldActionResponse) -> Void) {
        // Web domains get the same treatment, minus the per-app unshield: there is no equivalent
        // "let this one through" that doesn't reopen the whole category.
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
            // No live session: the shield is stale, so letting the app through is correct.
            lift(token: token)
            return .none
        }

        switch action {
        case .primaryButtonPressed:
            return .close                       // back to work; shield stays up

        case .secondaryButtonPressed:
            if session.accountability.requiresPasscodeToEnd {
                // A locked session's unshield needs a passcode, and an extension cannot ask for
                // one. `.defer` keeps the shield up and leaves the user on the shield screen —
                // the shield's own text already tells them to open Lockout to do this. Faking
                // success here would be the worst possible outcome: an unshielded app on a
                // session the partner believes is locked.
                recordUnshieldAttempt()
                return .defer
            }
            // Self-managed: the friction was the interruption, and it has been paid. Log it and
            // let them through.
            lift(token: token)
            recordUnshield(session: session)
            return .none

        @unknown default:
            return .close
        }
    }

    /// Remove just this app's shield, leaving the rest of the session protected. The store is
    /// named, so this touches only our own settings and never a parent's Screen Time rules.
    private func lift(token: ApplicationToken) {
        let store = ManagedSettingsStore(
            named: ManagedSettingsStore.Name("com.lockoutprotocol.lockout.focus"))
        var current = store.shield.applications ?? []
        current.remove(token)
        store.shield.applications = current.isEmpty ? nil : current
    }

    // MARK: - Recording
    //
    // The extension can't touch `SessionStore` (it is `@MainActor` and observable), and it must not
    // spend its tiny memory budget on the full judgement log. So it appends one line to a spool
    // file in the App Group, and the app folds it into the session and the judgement log the next
    // time it opens. Losing a spool line is survivable; crashing the extension is not.

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
