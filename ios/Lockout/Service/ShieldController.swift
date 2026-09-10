import DeviceActivity
import FamilyControls
import Foundation
import ManagedSettings

/// Applies and lifts the Screen Time shield — the iOS equivalent of the block overlay.
///
/// We do not enforce anything: iOS shields the tokens we hand it, in its own process, whether or
/// not this app is running. Hence no accessibility permission, no screen recording, no foreground
/// service and no keep-alive watchdog.
///
/// Two things silently do nothing if misconfigured — the `family-controls` entitlement and the App
/// Group — so both are checked rather than assumed. See `diagnose()`.
@MainActor
final class ShieldController: ObservableObject {

    static let shared = ShieldController()

    /// Named rather than default, so clearing ours can never clear a parent's Screen Time
    /// restrictions on a supervised device.
    static let storeName = ManagedSettingsStore.Name("com.lockoutprotocol.lockout.focus")

    private let store = ManagedSettingsStore(named: ShieldController.storeName)

    @Published private(set) var isShielding = false

    private init() {
        // The store persists across launches.
        isShielding = !(store.shield.applications?.isEmpty ?? true)
    }

    // MARK: - Authorization

    /// Must succeed before any shield can be applied; without it the picker shows nothing and
    /// the shield silently no-ops.
    func requestAuthorization() async -> String? {
        do {
            try await AuthorizationCenter.shared.requestAuthorization(for: .individual)
            return nil
        } catch {
            return "Screen Time access was refused. Without it iOS won't let this app shield "
                 + "anything, and nothing else here will work."
        }
    }

    var isAuthorized: Bool {
        AuthorizationCenter.shared.authorizationStatus == .approved
    }

    // MARK: - Applying

    /// Tokens arrive as base64 because that is the only form that survives the session file and
    /// an extension's process.
    func apply(tokens: [String]) {
        let decoded = Self.decode(tokens: tokens)
        guard !decoded.isEmpty else {
            clear()
            return
        }
        store.shield.applications = decoded
        isShielding = true
    }

    /// Lift the shield entirely. Called when a session ends, from every path that can end one.
    func clear() {
        store.shield.applications = nil
        store.shield.applicationCategories = nil
        isShielding = false
    }

    /// Unshield one app, leaving the rest of the session protected — the difference between an
    /// override and giving up.
    func unshield(token: String) {
        guard let decoded = Self.decode(tokens: [token]).first else { return }
        var current = store.shield.applications ?? []
        current.remove(decoded)
        store.shield.applications = current.isEmpty ? nil : current
        isShielding = !(store.shield.applications?.isEmpty ?? true)
    }

    // MARK: - Token coding

    /// `ApplicationToken` has no readable representation, so base64 of its encoded form is the
    /// portable handle used everywhere else.
    static func encode(token: ApplicationToken) -> String? {
        guard let data = try? JSONEncoder().encode(token) else { return nil }
        return data.base64EncodedString()
    }

    static func decode(tokens: [String]) -> Set<ApplicationToken> {
        var out = Set<ApplicationToken>()
        for raw in tokens {
            guard let data = Data(base64Encoded: raw),
                  let token = try? JSONDecoder().decode(ApplicationToken.self, from: data) else {
                continue        // uninstalled, or selected under a different authorization
            }
            out.insert(token)
        }
        return out
    }

    // MARK: - Scheduling

    /// The name iOS uses for our schedule. One long-running activity, replaced per session.
    static let activityName = DeviceActivityName("com.lockoutprotocol.lockout.session")

    private let center = DeviceActivityCenter()

    /// Ends at the session's end time, so the shield lifts even if the app is never reopened.
    /// Without this, "90 minutes" would mean "90 minutes, as long as you open the app afterwards".
    func schedule(until end: Date?) {
        center.stopMonitoring([Self.activityName])
        guard let end else { return }        // open-ended: nothing to schedule

        let calendar = Calendar.current
        let now = Date()
        let schedule = DeviceActivitySchedule(
            intervalStart: calendar.dateComponents([.hour, .minute], from: now),
            intervalEnd: calendar.dateComponents([.hour, .minute], from: end),
            repeats: false)
        do {
            try center.startMonitoring(Self.activityName, during: schedule)
        } catch {
            // Not worth blocking the session over: `SessionStore.current` also expires on read.
            NSLog("Lockout: could not register the session schedule: \(error)")
        }
    }

    func stopSchedule() {
        center.stopMonitoring([Self.activityName])
    }

    // MARK: - Diagnosis

    /// Both failures look identical from the user's side, so the settings screen lists them
    /// rather than leaving someone to guess.
    func diagnose() -> [String] {
        var problems: [String] = []
        if !isAuthorized {
            problems.append("Screen Time access hasn't been granted. Tap 'Allow Screen Time "
                          + "access' — without it iOS won't shield anything.")
        }
        if !SessionStore.containerIsShared {
            problems.append("The App Group isn't set up, so the shield screens can't see your "
                          + "session. Sessions will start but shields won't explain themselves. "
                          + "Check the App Group in every target's entitlements matches "
                          + "\(SessionStore.appGroup).")
        }
        return problems
    }
}
