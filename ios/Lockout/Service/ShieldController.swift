import DeviceActivity
import FamilyControls
import Foundation
import ManagedSettings

/// Applies and lifts the Screen Time shield — the iOS equivalent of the block overlay.
///
/// The important structural difference from the other three platforms: we do not enforce anything.
/// We hand iOS a set of opaque application tokens and iOS shields them, in its own process, with
/// its own UI, whether or not this app is running. That is why the iOS port needs no accessibility
/// permission, no screen recording permission, no foreground service, and no keep-alive watchdog —
/// three quarters of the tamper-resistance machinery on the other platforms exists to defend a
/// mechanism that iOS simply provides.
///
/// It also means the failure modes are different. There is nothing to crash mid-session, but there
/// are two things that will silently do nothing if misconfigured: the `family-controls`
/// entitlement (which Apple must grant per App ID) and the App Group (which the extensions read
/// the session through). Both are checked and reported rather than assumed — see `diagnose()`.
@MainActor
final class ShieldController: ObservableObject {

    static let shared = ShieldController()

    /// A named store, not the default one. `ManagedSettingsStore(named:)` keeps our settings in
    /// their own bucket so clearing ours can never clear a *parent's* Screen Time restrictions on
    /// a shared or supervised device.
    static let storeName = ManagedSettingsStore.Name("com.lockoutprotocol.lockout.focus")

    private let store = ManagedSettingsStore(named: ShieldController.storeName)

    @Published private(set) var isShielding = false

    private init() {
        // The store persists across launches, so reflect what is actually applied rather than
        // assuming a fresh launch means nothing is shielded.
        isShielding = !(store.shield.applications?.isEmpty ?? true)
    }

    // MARK: - Authorization

    /// Ask for Screen Time authorization. Must succeed before any shield can be applied; without
    /// it `FamilyActivityPicker` shows nothing and the shield silently no-ops.
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

    /// Shield the given tokens for the session.
    ///
    /// Tokens arrive as base64 strings because that is the only form that survives a trip through
    /// the session file and into an extension's process — `ApplicationToken` is `Codable` but not
    /// expressible as anything we can read.
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

    /// Temporarily unshield ONE app — what "I'm on task" does on a self-managed session, and what
    /// a correct passcode does on a locked one.
    ///
    /// Removing just the one token rather than clearing the store is the point: the rest of the
    /// session stays protected, which is the difference between an override and giving up.
    func unshield(token: String) {
        guard let decoded = Self.decode(tokens: [token]).first else { return }
        var current = store.shield.applications ?? []
        current.remove(decoded)
        store.shield.applications = current.isEmpty ? nil : current
        isShielding = !(store.shield.applications?.isEmpty ?? true)
    }

    // MARK: - Token coding

    /// `ApplicationToken` round-trips through `Codable` but has no readable representation, so
    /// base64 of its encoded form is the portable handle used everywhere else in the app.
    static func encode(token: ApplicationToken) -> String? {
        guard let data = try? JSONEncoder().encode(token) else { return nil }
        return data.base64EncodedString()
    }

    static func decode(tokens: [String]) -> Set<ApplicationToken> {
        var out = Set<ApplicationToken>()
        for raw in tokens {
            guard let data = Data(base64Encoded: raw),
                  let token = try? JSONDecoder().decode(ApplicationToken.self, from: data) else {
                // A token that no longer decodes means the app was uninstalled, or the selection
                // was made under a different Screen Time authorization. Skipping it is right;
                // failing the whole session over one stale token is not.
                continue
            }
            out.insert(token)
        }
        return out
    }

    // MARK: - Scheduling

    /// The name iOS uses for our schedule. One long-running activity, replaced per session.
    static let activityName = DeviceActivityName("com.lockoutprotocol.lockout.session")

    private let center = DeviceActivityCenter()

    /// Register a schedule that ends at the session's end time, so the shield lifts even if the
    /// app is never opened again.
    ///
    /// This is the part that makes a timed session trustworthy. Without it, "90 minutes" would
    /// really mean "90 minutes, as long as you open the app afterwards" — and a shield that
    /// outlives its session is exactly the kind of thing that gets a focus app deleted.
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
            // A schedule we couldn't register is a real problem, but not one worth blocking the
            // session over: `SessionStore.current` also expires on read, so opening the app
            // afterwards still ends it. The diagnosis surfaces it.
            NSLog("Lockout: could not register the session schedule: \(error)")
        }
    }

    func stopSchedule() {
        center.stopMonitoring([Self.activityName])
    }

    // MARK: - Diagnosis

    /// The two things that silently break iOS shielding, checked rather than assumed.
    ///
    /// Both failures look identical from the user's side — you start a session and nothing is
    /// shielded — so the settings screen shows this list instead of leaving someone to guess.
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
