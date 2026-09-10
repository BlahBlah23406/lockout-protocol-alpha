import Foundation

/// The two accountability levels, differing only in who holds the exit.
///
/// On iOS the anti-lockout guarantee is the system's job: the shield is drawn by iOS, always has a
/// close action, and never covers the home screen, Settings, Phone or Messages.
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
/// The shape matches the other three ports so the judgement log and the learner stay one format,
/// but the mechanism differs: no iOS app can see another app's screen, so the model answers
/// "which of my apps should be shut for this task?" rather than "is this screen on task?".
/// See `ios/README.md` for the trade-off that makes.
struct FocusSession: Codable, Identifiable, Sendable {

    static let defaultInterval = 120
    static let minInterval = 15
    static let maxInterval = 3600

    var id: String
    var task: String
    var startedAt: Date
    /// 0 means open-ended. Not offered for `.locked`, same as everywhere else.
    var plannedMinutes: Int
    /// Carried for schema parity. iOS does not poll: the shield is applied once and the system
    /// enforces it.
    var intervalSeconds: Int
    var accountability: Accountability
    /// Base64-encoded `ApplicationToken`s. iOS never gives an app the real bundle ids of other
    /// apps, which is why the watchlist cannot be typed in by hand.
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

    /// For the `DeviceActivitySchedule` that lifts the shield even if the app is never reopened.
    var endsAt: Date? {
        guard plannedMinutes > 0 else { return nil }
        return startedAt.addingTimeInterval(Double(plannedMinutes * 60))
    }
}

/// The one active session, in the App Group container.
///
/// A Screen Time extension runs in its own process and cannot reach the app's sandbox, so the
/// session has to live somewhere all four processes can see.
@MainActor
final class SessionStore: ObservableObject {

    static let shared = SessionStore()

    /// Must match the App Group in every target's entitlements: if they disagree, the app works
    /// and the shield silently does nothing.
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

    /// The shared container, falling back to the app's own documents directory so a
    /// misconfigured App Group doesn't crash on launch. `containerIsShared` reports the fallback
    /// so the UI can say so.
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

    /// The live session, or nil. Expiry is evaluated on read.
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

/// Read-only session access for the Screen Time extensions, which cannot use `SessionStore`:
/// it is `@MainActor` and observable, and an extension runs with a few megabytes to spend.
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
