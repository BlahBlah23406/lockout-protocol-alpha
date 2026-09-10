import Foundation

/// Client side of the experimental false-alarm learner.
///
/// The learner is offline Python at `learner/`; this reads the one artefact it produces and turns
/// it into extra prompt lines, a pre-allow, and a confidence threshold.
///
/// Everything here fails soft: a missing, stale, corrupt or future-schema policy must leave the
/// app behaving exactly as it does with no learning at all.
enum LearnedPolicy {

    /// A policy claiming a newer schema is ignored rather than half-read: the parts we'd drop
    /// might be the safety limits.
    static let supportedSchema = 1

    /// The ceiling on how far learning may erode the monitor. It lives in the app so that
    /// hand-editing the generated file cannot lift it.
    static let maxThreshold = 0.85
    static let maxSuffixChars = 1200
    static let maxAgeDays: TimeInterval = 60

    struct Decision {
        var promptSuffix: String = ""
        var preAllow: Bool = false
        var blockThreshold: Double = 0
    }

    static var fileURL: URL = {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)
            .first ?? FileManager.default.temporaryDirectory
        return base.appendingPathComponent("LockoutProtocol/focus_policy.json")
    }()

    private static var cachedModified: Date?
    private static var cached: [String: Any]?

    /// Read + cache the policy file, reloading only when it changes on disk.
    static func load() -> [String: Any] {
        let attrs = try? FileManager.default.attributesOfItem(atPath: fileURL.path)
        guard let modified = attrs?[.modificationDate] as? Date else {
            cachedModified = nil; cached = nil
            return [:]
        }
        if cachedModified == modified, let cached { return cached }

        var data: [String: Any] = [:]
        if let raw = try? Data(contentsOf: fileURL),
           let obj = try? JSONSerialization.jsonObject(with: raw) as? [String: Any] {
            data = obj
        }
        if data["schema"] as? Int != supportedSchema { data = [:] }
        // A policy learned two months ago describes a different person's week.
        if let generated = data["generated_at"] as? Double,
           Date().timeIntervalSince1970 - generated > maxAgeDays * 86400 {
            data = [:]
        }

        cachedModified = modified
        cached = data
        return data
    }

    /// The one call the monitor makes. Always returns a usable value.
    ///
    /// The artefact carries a pre-expanded `decisions` map keyed by `"<task-cluster>|<app>"`, so
    /// every client is a string lookup rather than a reimplementation of the learner's matching.
    static func decide(task: String, app: String, title: String = "") -> Decision {
        let policy = load()
        guard !policy.isEmpty else { return Decision() }

        guard let decisions = policy["decisions"] as? [String: [String: Any]] else {
            return Decision()
        }
        let key = lookupKey(task: task, app: app)
        guard let entry = decisions[key] ?? decisions["*|\(app)"] else { return Decision() }

        var decision = Decision()
        decision.promptSuffix = String((entry["prompt_suffix"] as? String ?? "")
            .prefix(maxSuffixChars))
        decision.preAllow = entry["pre_allow"] as? Bool ?? false
        let raw = (entry["block_threshold"] as? NSNumber)?.doubleValue ?? 0
        decision.blockThreshold = min(max(raw, 0), maxThreshold)

        // An app-wide pre-allow with no title evidence would silently un-watch a whole app.
        if decision.preAllow, let patterns = entry["title_patterns"] as? [String], !patterns.isEmpty {
            let lowered = title.lowercased()
            decision.preAllow = patterns.contains { lowered.contains($0.lowercased()) }
        }
        return decision
    }

    static func promptSuffix(task: String, app: String, title: String = "") -> String {
        decide(task: task, app: app, title: title).promptSuffix
    }

    /// Must agree character for character with `learner/policy.py:lookup_key`, or a learned
    /// policy silently never matches. Lowercase, alphanumerics only, stopwords and short words
    /// dropped, first four joined with "-".
    ///
    /// The app id is lower-cased too: a macOS bundle id has uppercase in it, and skipping this
    /// made every macOS lookup miss.
    static func lookupKey(task: String, app: String) -> String {
        let stop: Set<String> = ["the", "a", "an", "my", "for", "on", "to", "of", "and", "in",
                                 "working", "work", "doing", "do", "some", "this", "that"]
        // Rebuilt into a String before splitting: chaining off `map` leaves enough `String.init`
        // overloads in play that the compiler reports "ambiguous use of 'prefix'".
        let flattened = String(task.lowercased().map { $0.isLetter || $0.isNumber ? $0 : " " })
        let words: [String] = flattened
            .split(separator: " ")
            .map { String($0) }
            .filter { !stop.contains($0) && $0.count > 2 }
        let appKey = app.trimmingCharacters(in: .whitespaces).lowercased()
        return "\(words.prefix(4).joined(separator: "-"))|\(appKey)"
    }

    /// One line for the settings screen, so "learning is on" is never an unverifiable claim.
    static func status() -> String {
        let policy = load()
        guard !policy.isEmpty else { return "no policy learned yet" }
        let exemplars = policy["exemplar_count"] as? Int ?? 0
        let signatures = policy["signature_count"] as? Int ?? 0
        let stamp: String
        if let when = policy["generated_at"] as? Double {
            let formatter = DateFormatter()
            formatter.dateFormat = "yyyy-MM-dd"
            stamp = formatter.string(from: Date(timeIntervalSince1970: when))
        } else {
            stamp = "unknown date"
        }
        return "\(exemplars) exemplar(s), \(signatures) allowance(s), learned \(stamp)"
    }
}
