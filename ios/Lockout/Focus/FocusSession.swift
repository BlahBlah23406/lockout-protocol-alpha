import Foundation

/// Which accountability level a session was started at.
///
/// Same two levels as every other platform, and the difference is still *who holds the exit*:
///
/// - `.selfManaged` — the shield still goes up and the detour still costs a deliberate tap, but
///   you can lift it yourself with no passcode. Nobody else is told.
/// - `.locked` — lifting the shield needs the passcode, and both the block and the lift are pushed
///   to your accountability partner's private ntfy link.
///
/// On iOS the anti-lockout guarantee is partly the system's job rather than ours: the Screen Time
/// shield is drawn by iOS, always has a "close" action, and never covers the home screen, Settings,
/// Phone, or Messages. We could not trap someone here even if we wanted to — which is a genuinely
/// nicer property than the one we have to engineer by hand on the other three platforms.
enum Accountability: String, Codable, CaseIterable, Sendable {
    case selfManaged = "self"
    case locked = "locked"

    var title: String {
        switch self {
        case .selfManaged: return "Self-managed"
        case .locked: return "Locked"
        }
    }

    var blurb: String {
        switch self {
        case .selfManaged:
            return "Shielded apps can be unshielded by you, no passcode. Nobody is told. "
                 + "Start here."
        case .locked:
            return "Unshielding needs the passcode, and every shield and unshield is pushed to "
                 + "your accountability partner."
        }
    }

    var requiresPasscodeToEnd: Bool { self == .locked }
    var alertsPartner: Bool { self == .locked }
}

/// One declared stretch of work.
///
/// The shape matches the Windows, macOS and Android ports so the judgement log and the learner
/// stay one format across four clients — but the *mechanism* underneath is different, and it is
/// worth being blunt about why.
///
/// On the desktop and on Android the app screenshots the foreground app and asks a vision model
/// "is this screen part of the declared task?". **On iOS that is impossible.** No public API lets
/// an app see another app's content, and the sandbox is not going to be talked out of it. So the
/// question the model answers here is a different one:
///
///     desktop / Android:  "you said math test prep — is THIS SCREEN part of it?"
///     iOS:                "you said math test prep — WHICH OF MY APPS should be shut for it?"
///
/// That is a text-level judgement over app names, and it is one a model is good at. It is weaker
/// than the screen check in one specific way — YouTube is either shielded or not, so it cannot
/// tell a Khan Academy lecture from a gaming stream — and stronger in another: the shield is drawn
/// by iOS itself, so it cannot be swiped away, and there is no screenshot of your screen leaving
/// the device at all. See `ios/README.md`.
struct FocusSession: Codable, Identifiable, Sendable {

    static let defaultInterval = 120
    static let minInterval = 15
    static let maxInterval = 3600

    var id: String
    var task: String
    var startedAt: Date
    /// 0 means open-ended. Not offered for `.locked`, same as everywhere else.
    var plannedMinutes: Int
    /// Carried for schema parity with the other ports. iOS does not poll on an interval — the
    /// shield is applied once and iOS enforces it — so this only affects how often the app
    /// re-asks the model whether the shield plan should change (e.g. you edited the task).
    var intervalSeconds: Int
    var accountability: Accountability
    /// Opaque `ApplicationToken` identifiers, base64-encoded. iOS never gives an app the real
    /// bundle ids of the user's other apps; the picker hands back tokens the system can resolve
    /// and we cannot. That is why the iOS watchlist cannot be typed in by hand.
    var shieldedTokens: [String]
    var providerId: String
    var endedAt: Date?
    var endedReason: String
    var unshieldCount: Int

    init(task: String,
         plannedMinutes: Int = 0,
         intervalSeconds: Int = FocusSession.defaultInterval,
         accountability: Accountability = .selfManaged,
         shieldedTokens: [String] = [],
         providerId: String = "") {
        self.id = "fs_" + UUID().uuidString.prefix(10).lowercased()
        self.task = task.trimmingCharacters(in: .whitespacesAndNewlines)
        self.startedAt = Date()
        self.plannedMinutes = max(plannedMinutes, 0)
        self.intervalSeconds = Self.clampInterval(intervalSeconds)
        self.accountability = accountability
        self.shieldedTokens = shieldedTokens
        self.providerId = providerId
        self.endedAt = nil
        self.endedReason = ""
        self.unshieldCount = 0
    }

    static func clampInterval(_ seconds: Int) -> Int {
        min(max(seconds, minInterval), maxInterval)
    }

    var isActive: Bool { endedAt == nil }
    var elapsed: TimeInterval { max(Date().timeIntervalSince(startedAt), 0) }

    var remaining: TimeInterval? {
        guard plannedMinutes > 0 else { return nil }
        return max(Double(plannedMinutes * 60) - elapsed, 0)
    }

    var isOver: Bool {
        guard let remaining else { return false }
        return remaining <= 0
    }

    var remainingText: String {
        guard let remaining else { return "open-ended" }
        return "\(Int(remaining) / 60)m \(String(format: "%02d", Int(remaining) % 60))s left"
    }

    /// When the session should end, for the `DeviceActivitySchedule` that lifts the shield even if
    /// the app is never opened again.
    var endsAt: Date? {
        guard plannedMinutes > 0 else { return nil }
        return startedAt.addingTimeInterval(Double(plannedMinutes * 60))
    }
}

/// The one active session, in the App Group container so the shield and monitor extensions can
/// read it too.
///
/// This is not the same problem as on the other platforms. A Screen Time extension runs in its own
/// process, is launched by the system on its own schedule, and cannot reach the app's own sandbox —
/// so the session has to live somewhere all four processes can see. That is the App Group, and it
/// is why this store writes a plain file rather than using `UserDefaults.standard`.
@MainActor
final class SessionStore: ObservableObject {

    static let shared = SessionStore()

    /// Must match the App Group in every target's entitlements. If this string and the entitlement
    /// disagree, the app works and the shield silently does nothing — so it is defined once.
    static let appGroup = "group.com.lockoutprotocol.lockout"

    @Published private(set) var stored: FocusSession?

    private let sessionURL: URL
    private let historyURL: URL

    private init() {
        let dir = Self.containerDirectory()
        sessionURL = dir.appendingPathComponent("focus_session.json")
        historyURL = dir.appendingPathComponent("focus_history.jsonl")
        stored = Self.load(from: sessionURL)
        if let s = stored, !s.isActive { stored = nil }
    }

    /// The shared container, or the app's own documents directory as a fallback.
    ///
    /// The fallback matters: if the App Group is misconfigured the app must still run rather than
    /// crash on launch. It will not shield correctly, and `containerIsShared` reports that so the
    /// UI can say so out loud instead of pretending.
    static func containerDirectory() -> URL {
        if let shared = FileManager.default.containerURL(
            forSecurityApplicationGroupIdentifier: appGroup) {
            return shared
        }
        return FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first
            ?? FileManager.default.temporaryDirectory
    }

    static var containerIsShared: Bool {
        FileManager.default.containerURL(
            forSecurityApplicationGroupIdentifier: appGroup) != nil
    }

    /// The live session, or nil. Expiry is evaluated on read, so a phone that was off past the end
    /// time still ends cleanly.
    var current: FocusSession? {
        guard let s = stored else { return nil }
        if s.isOver {
            end(reason: "time's up")
            return nil
        }
        return stored
    }

    var isActive: Bool { current != nil }

    @discardableResult
    func start(_ session: FocusSession) -> FocusSession {
        if stored != nil { end(reason: "replaced by a new session") }
        stored = session
        save()
        return session
    }

    func end(reason: String = "ended") {
        guard var s = stored else { return }
        s.endedAt = Date()
        s.endedReason = reason
        archive(s)
        stored = nil
        save()
    }

    func recordUnshield() {
        guard var s = stored else { return }
        s.unshieldCount += 1
        stored = s
        save()
    }

    private static func load(from url: URL) -> FocusSession? {
        guard let data = try? Data(contentsOf: url) else { return nil }
        return try? JSONDecoder().decode(FocusSession.self, from: data)
    }

    private func save() {
        guard let s = stored else {
            try? FileManager.default.removeItem(at: sessionURL)
            return
        }
        guard let data = try? JSONEncoder().encode(s) else { return }
        try? data.write(to: sessionURL, options: .atomic)
    }

    private func archive(_ session: FocusSession) {
        guard var data = try? JSONEncoder().encode(session) else { return }
        data.append(contentsOf: [0x0A])
        if let handle = try? FileHandle(forWritingTo: historyURL) {
            defer { try? handle.close() }
            try? handle.seekToEnd()
            try? handle.write(contentsOf: data)
        } else {
            try? data.write(to: historyURL, options: .atomic)
        }
    }

    func history(limit: Int = 50) -> [FocusSession] {
        guard let text = try? String(contentsOf: historyURL, encoding: .utf8) else { return [] }
        let decoder = JSONDecoder()
        return text.split(separator: "\n").suffix(limit).compactMap {
            guard let data = $0.data(using: .utf8) else { return nil }
            return try? decoder.decode(FocusSession.self, from: data)
        }
    }
}

/// Read-only session access for the Screen Time extensions.
///
/// The extensions cannot use `SessionStore` — it is `@MainActor` and `ObservableObject`, and an
/// extension is launched by the system with no app running and a hard memory ceiling (about 6 MB
/// for a shield configuration extension). This is the minimum needed to answer "what session is
/// running, and at what level", with no observation machinery attached.
enum SharedSession {

    static func current() -> FocusSession? {
        let url = SessionStore.containerDirectory()
            .appendingPathComponent("focus_session.json")
        guard let data = try? Data(contentsOf: url),
              let session = try? JSONDecoder().decode(FocusSession.self, from: data),
              session.isActive, !session.isOver else {
            return nil
        }
        return session
    }
}
