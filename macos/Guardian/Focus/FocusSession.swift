import Foundation

/// The two accountability levels, differing only in who holds the exit.
///
/// Neither can trap you: closing a blocked app is always passcode-free. What `.locked` costs is
/// the override, not the escape. See `SAFEGUARDS.md`.
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
            return "It blocks you and logs it — but you can wave it away yourself. "
                 + "No passcode, nobody is told. Start here."
        case .locked:
            return "Overriding a block needs the passcode, and every block and override is pushed "
                 + "to your accountability partner. Closing the app still always works."
        }
    }

    /// Only a locked session holds its own exit; you can always quit the app.
    var requiresPasscodeToEnd: Bool { self == .locked }
    var alertsPartner: Bool { self == .locked }
}

/// One declared stretch of work: a task, a length, a set of apps, checked every
/// `intervalSeconds`. When no session is running, nothing is captured at all.
struct FocusSession: Codable, Identifiable, Sendable {

    /// Below a minute you pay for inference constantly; above five a detour has already eaten
    /// the block it should have prevented.
    static let defaultInterval = 120
    static let minInterval = 15
    static let maxInterval = 3600

    var id: String
    var task: String
    var startedAt: Date
    /// 0 = open-ended. Not offered for `.locked`: open-ended plus a forgotten passcode is the
    /// one shape that could genuinely trap someone.
    var plannedMinutes: Int
    var intervalSeconds: Int
    var accountability: Accountability
    /// This-session-only adjustments over the saved default watchlist.
    var extraApps: Set<String>
    var allowedApps: Set<String>
    var providerId: String
    var endedAt: Date?
    var endedReason: String
    var checks: Int
    var offTaskCount: Int
    var overrideCount: Int
    var pausedUntil: Date?

    init(task: String,
         plannedMinutes: Int = 0,
         intervalSeconds: Int = FocusSession.defaultInterval,
         accountability: Accountability = .selfManaged,
         extraApps: Set<String> = [],
         allowedApps: Set<String> = [],
         providerId: String = "") {
        self.id = "fs_" + UUID().uuidString.prefix(10).lowercased()
        self.task = task.trimmingCharacters(in: .whitespacesAndNewlines)
        self.startedAt = Date()
        self.plannedMinutes = max(plannedMinutes, 0)
        self.intervalSeconds = Self.clampInterval(intervalSeconds)
        self.accountability = accountability
        self.extraApps = extraApps
        self.allowedApps = allowedApps
        self.providerId = providerId
        self.endedAt = nil
        self.endedReason = ""
        self.checks = 0
        self.offTaskCount = 0
        self.overrideCount = 0
        self.pausedUntil = nil
    }

    static func clampInterval(_ seconds: Int) -> Int {
        min(max(seconds, minInterval), maxInterval)
    }

    // MARK: - Watchlist

    /// Saved defaults, plus anything added just for today, minus anything excused just for today.
    /// Stored as a delta rather than a copy, so editing the defaults mid-session takes effect.
    func watchlist(defaults: Set<String>) -> Set<String> {
        defaults.union(extraApps).subtracting(allowedApps)
    }

    // MARK: - Lifecycle

    var isActive: Bool { endedAt == nil }
    var elapsed: TimeInterval { max(Date().timeIntervalSince(startedAt), 0) }

    /// Seconds left, or nil for an open-ended session.
    var remaining: TimeInterval? {
        guard plannedMinutes > 0 else { return nil }
        return max(Double(plannedMinutes * 60) - elapsed, 0)
    }

    var isOver: Bool {
        guard let remaining else { return false }
        return remaining <= 0
    }

    var isPaused: Bool {
        guard let pausedUntil else { return false }
        return pausedUntil > Date()
    }

    var remainingText: String {
        guard let remaining else { return "open-ended" }
        return "\(Int(remaining) / 60)m \(String(format: "%02d", Int(remaining) % 60))s left"
    }
}

/// The one active session, persisted, plus an append-only history.
///
/// Persistence is load-bearing: if force-quitting silently cancelled a locked session, "locked"
/// would be worth nothing.
@MainActor
final class SessionStore: ObservableObject {

    static let shared = SessionStore()

    @Published private(set) var stored: FocusSession?

    private let sessionURL: URL
    private let historyURL: URL

    private init() {
        let dir = Self.supportDirectory()
        sessionURL = dir.appendingPathComponent("focus_session.json")
        historyURL = dir.appendingPathComponent("focus_history.jsonl")
        stored = Self.load(from: sessionURL)
        if let s = stored, !s.isActive { stored = nil }
    }

    private static func supportDirectory() -> URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)
            .first ?? FileManager.default.temporaryDirectory
        let dir = base.appendingPathComponent("LockoutProtocol", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }

    // MARK: - Accessors

    /// The live session, or nil. Expiry is evaluated on read, so a Mac that slept past the end
    /// time still ends its session cleanly.
    var current: FocusSession? {
        guard let s = stored else { return nil }
        if s.isOver {
            end(reason: "time's up")
            return nil
        }
        return stored
    }

    var isActive: Bool { current != nil }

    // MARK: - Mutations

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

    /// Used by the block screen's override, so the user isn't re-blocked mid-sentence.
    func pause(seconds: TimeInterval) {
        guard var s = stored else { return }
        s.pausedUntil = Date().addingTimeInterval(max(seconds, 0))
        stored = s
        save()
    }

    func recordCheck(offTask: Bool) {
        guard var s = stored else { return }
        s.checks += 1
        if offTask { s.offTaskCount += 1 }
        stored = s
        save()
    }

    func recordOverride() {
        guard var s = stored else { return }
        s.overrideCount += 1
        stored = s
        save()
    }

    func addSessionApp(_ bundleId: String) {
        guard var s = stored else { return }
        s.extraApps.insert(bundleId)
        s.allowedApps.remove(bundleId)
        stored = s
        save()
    }

    func allowSessionApp(_ bundleId: String) {
        guard var s = stored else { return }
        s.allowedApps.insert(bundleId)
        s.extraApps.remove(bundleId)
        stored = s
        save()
    }

    // MARK: - Persistence

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
        data.append(contentsOf: [0x0A])                       // newline — this is JSONL
        if let handle = try? FileHandle(forWritingTo: historyURL) {
            defer { try? handle.close() }
            try? handle.seekToEnd()
            try? handle.write(contentsOf: data)
        } else {
            try? data.write(to: historyURL, options: .atomic)
        }
    }

    /// Finished sessions, newest last. A torn final line after a hard kill is skipped.
    func history(limit: Int = 50) -> [FocusSession] {
        guard let text = try? String(contentsOf: historyURL, encoding: .utf8) else { return [] }
        let decoder = JSONDecoder()
        return text.split(separator: "\n").suffix(limit).compactMap {
            guard let data = $0.data(using: .utf8) else { return nil }
            return try? decoder.decode(FocusSession.self, from: data)
        }
    }
}
